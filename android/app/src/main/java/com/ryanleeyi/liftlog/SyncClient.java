package com.ryanleeyi.liftlog;

import org.json.JSONException;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.util.HashSet;
import java.util.Set;

/** F144 的最小同步迴圈：同一 outbox 先 push，receipt commit 後再以 cursor pull。 */
final class SyncClient {
    static final int MAX_PUSH_COUNT = 500;
    static final int MAX_PUSH_BYTES = 1024 * 1024;
    static final long MAX_RETRY_MILLIS = 15 * 60 * 1000L;

    interface Transport {
        JSONObject push(JSONObject body) throws IOException, JSONException;
        JSONObject pull(long cursor) throws IOException, JSONException;
    }

    interface RandomSource {
        double nextDouble();
    }

    static final class TransportFailure extends IOException {
        final String errorCode;
        final boolean retryable;

        TransportFailure(String errorCode, boolean retryable) {
            super(errorCode);
            this.errorCode = errorCode;
            this.retryable = retryable;
        }
    }

    static final class Result {
        final String state;
        final int pending;
        final long cursor;

        Result(String state, int pending, long cursor) {
            this.state = state;
            this.pending = pending;
            this.cursor = cursor;
        }
    }

    private final LocalStore store;
    private final String deviceId;
    private final Transport transport;
    private final RandomSource random;

    SyncClient(LocalStore store, String deviceId, Transport transport, RandomSource random) {
        this.store = store;
        this.deviceId = deviceId;
        this.transport = transport;
        this.random = random;
    }

    Result syncOnce(long nowMillis) {
        JSONObject body = null;
        try {
            while (true) {
                body = store.pendingPushBody(
                    deviceId, MAX_PUSH_COUNT, MAX_PUSH_BYTES, nowMillis
                );
                if (body.getJSONArray("mutations").length() == 0) break;
                JSONObject pushed = transport.push(body);
                validatePushResponse(body, pushed);
                store.applyPushResponse(pushed, nowMillis);
            }
            boolean hasMore;
            do {
                long cursor = store.serverCursor();
                JSONObject pulled = transport.pull(cursor);
                store.applyPullPage(pulled);
                hasMore = pulled.getBoolean("has_more");
                if (hasMore && store.serverCursor() <= cursor) {
                    throw new IllegalArgumentException("pull pagination 未前進");
                }
            } while (hasMore);
            store.markSyncSuccess(nowMillis);
            JSONObject status = store.syncStatus();
            return new Result(
                status.getString("state"), status.getInt("pending"), store.serverCursor()
            );
        } catch (TransportFailure error) {
            if (error.retryable) {
                scheduleRetry(body, error.errorCode, nowMillis);
            } else if (isSessionFailure(error.errorCode)) {
                store.markSyncError(error.errorCode);
            } else if (!hasPushMutations(body)) {
                store.markSyncError(error.errorCode);
            } else {
                store.markPushPermanentFailure(body, error.errorCode);
            }
            return new Result("error", store.pendingMutationCount(), store.serverCursor());
        } catch (IOException error) {
            scheduleRetry(body, "offline", nowMillis);
            return new Result("offline", store.pendingMutationCount(), store.serverCursor());
        } catch (LocalStore.BatchTooLarge error) {
            store.markMutationFailed(error.mutationId, "payload_too_large");
            return new Result("error", store.pendingMutationCount(), store.serverCursor());
        } catch (JSONException | IllegalArgumentException error) {
            scheduleRetry(body, "sync_error", nowMillis);
            return new Result("error", store.pendingMutationCount(), store.serverCursor());
        } catch (RuntimeException error) {
            // SQLite constraint/lock 與其他本機 apply failure 也必須留下可見 error 與 retry。
            scheduleRetry(body, "sync_error", nowMillis);
            return new Result("error", store.pendingMutationCount(), store.serverCursor());
        }
    }

    private void scheduleRetry(JSONObject body, String errorCode, long nowMillis) {
        int attempt = hasPushMutations(body)
            ? store.nextAttemptNumber(body)
            : store.nextPullAttemptNumber();
        long retryAt = nowMillis + retryDelayMillis(attempt, random.nextDouble());
        if (hasPushMutations(body)) store.markPushFailure(body, errorCode, retryAt);
        else store.markPullFailure(errorCode, retryAt);
    }

    private static boolean hasPushMutations(JSONObject body) {
        JSONArray mutations = body == null ? null : body.optJSONArray("mutations");
        return mutations != null && mutations.length() > 0;
    }

    static long retryDelayMillis(int attempt, double randomValue) {
        int shift = Math.max(0, Math.min(attempt - 1, 17));
        long base = Math.min(MAX_RETRY_MILLIS, 5_000L << shift);
        double boundedRandom = Math.max(0.0, Math.min(1.0, randomValue));
        long jitter = (long) (base * 0.25 * boundedRandom);
        return Math.min(MAX_RETRY_MILLIS, base + jitter);
    }

    private static void validatePushResponse(JSONObject request, JSONObject response)
        throws JSONException {
        Set<String> expected = mutationIds(request.getJSONArray("mutations"));
        Set<String> seen = new HashSet<>();
        collectReceiptIds(response.getJSONArray("accepted"), expected, seen);
        collectReceiptIds(response.getJSONArray("conflicts"), expected, seen);
        if (!seen.equals(expected)) throw new IllegalArgumentException("push receipt 不完整");
    }

    private static Set<String> mutationIds(JSONArray items) throws JSONException {
        Set<String> ids = new HashSet<>();
        for (int index = 0; index < items.length(); index++) {
            ids.add(items.getJSONObject(index).getString("mutation_id"));
        }
        return ids;
    }

    private static void collectReceiptIds(
        JSONArray items, Set<String> expected, Set<String> seen
    ) throws JSONException {
        for (int index = 0; index < items.length(); index++) {
            String id = items.getJSONObject(index).getString("mutation_id");
            if (!expected.contains(id) || !seen.add(id)) {
                throw new IllegalArgumentException("push receipt 不合法");
            }
        }
    }

    private static boolean isSessionFailure(String errorCode) {
        return "auth_required".equals(errorCode)
            || "secure_store_unavailable".equals(errorCode)
            || errorCode != null && errorCode.startsWith("auth_refresh_");
    }
}
