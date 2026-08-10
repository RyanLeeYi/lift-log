package com.ryanleeyi.liftlog;

import android.app.Activity;
import android.os.Build;
import android.os.CancellationSignal;

import androidx.core.content.ContextCompat;
import androidx.credentials.Credential;
import androidx.credentials.CredentialManager;
import androidx.credentials.CredentialManagerCallback;
import androidx.credentials.CustomCredential;
import androidx.credentials.GetCredentialRequest;
import androidx.credentials.GetCredentialResponse;
import androidx.credentials.exceptions.GetCredentialException;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption;
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential;

/** F141 Android Google Sign-In 與加密 session 的最薄 Capacitor bridge。 */
@CapacitorPlugin(name = "AuthSession")
public class AuthSessionPlugin extends Plugin {

    @PluginMethod
    public void loadSession(PluginCall call) {
        String deviceId = SecureStore.deviceId(getContext());
        if (deviceId == null) {
            call.reject("安全儲存不可用");
            return;
        }
        JSObject result = new JSObject();
        result.put("deviceId", deviceId);
        result.put("deviceName", deviceName());
        result.put("accessToken", SecureStore.accessToken(getContext()));
        result.put("refreshToken", SecureStore.refreshToken(getContext()));
        result.put("accessExpiresAt", SecureStore.accessExpiresAt(getContext()));
        call.resolve(result);
    }

    @PluginMethod
    public void saveSession(PluginCall call) {
        Long expiresAt = call.getLong("accessExpiresAt");
        if (expiresAt == null || !SecureStore.saveAuthSession(
            getContext(),
            call.getString("accessToken"),
            call.getString("refreshToken"),
            expiresAt
        )) {
            call.reject("無法安全保存登入狀態");
            return;
        }
        call.resolve();
    }

    @PluginMethod
    public void clearSession(PluginCall call) {
        SecureStore.clearAuthSession(getContext());
        call.resolve();
    }

    @PluginMethod
    public void googleSignIn(PluginCall call) {
        String clientId = call.getString("clientId");
        String nonce = call.getString("nonce");
        Activity activity = getActivity();
        String deviceId = SecureStore.deviceId(getContext());
        if (activity == null || clientId == null || clientId.trim().isEmpty()
            || nonce == null || nonce.length() < 16 || deviceId == null) {
            call.reject("Google 登入設定無效");
            return;
        }

        GetSignInWithGoogleOption option = new GetSignInWithGoogleOption.Builder(clientId)
            .setNonce(nonce)
            .build();
        GetCredentialRequest request = new GetCredentialRequest.Builder()
            .addCredentialOption(option)
            .build();

        CredentialManager.create(activity).getCredentialAsync(
            activity,
            request,
            new CancellationSignal(),
            ContextCompat.getMainExecutor(activity),
            new CredentialManagerCallback<GetCredentialResponse, GetCredentialException>() {
                @Override
                public void onResult(GetCredentialResponse response) {
                    Credential credential = response.getCredential();
                    if (!(credential instanceof CustomCredential custom)
                        || !GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL.equals(
                            custom.getType())) {
                        call.reject("Google 未回傳可用的登入憑證");
                        return;
                    }
                    try {
                        GoogleIdTokenCredential google = GoogleIdTokenCredential.createFrom(
                            custom.getData());
                        JSObject result = new JSObject();
                        result.put("idToken", google.getIdToken());
                        result.put("deviceId", deviceId);
                        result.put("deviceName", deviceName());
                        call.resolve(result);
                    } catch (Exception error) {
                        call.reject("Google 登入憑證無法解析");
                    }
                }

                @Override
                public void onError(GetCredentialException error) {
                    call.reject("Google 登入未完成");
                }
            }
        );
    }

    private static String deviceName() {
        String maker = Build.MANUFACTURER == null ? "Android" : Build.MANUFACTURER.trim();
        String model = Build.MODEL == null ? "device" : Build.MODEL.trim();
        return maker.equalsIgnoreCase(model) ? model : (maker + " " + model).trim();
    }
}
