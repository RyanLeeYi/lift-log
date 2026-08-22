# F153 條文更新：自填 LLM key 改為「每次請求交給 server 代打」

2026-08-22。F153 的 frozen acceptance 寫「LLM API key 支援兩種來源：server `.env` 與
使用者自填（**存本機，不上傳 server**）」。F164 簽核時 Ryan 選了 (a) **server 代打**，
所以自填的 key 每次請求會以 `X-LLM-API-Key` header 交給 server。

**為什麼改**：前端直打 LLM 供應商，等於要在瀏覽器裡再實作一套 tool-calling 迴圈，
那就是 E1「不得為內建對話另開第二條寫入路徑」明文禁止的東西。

**代價與界線**（(a) 保留了原條文真正在意的事：key 不變成伺服器的持久資產）：
key 只活在單一請求的生命週期內——不寫任何 DB、不寫 log、不回傳給任何 client，
落地與否有測試釘住（`tests/test_chat.py::test_user_supplied_key_wins_and_never_comes_back`
會掃過 tmp 內所有 `.db` 的位元組）。改變的是「傳輸中會經過 server」，
不是「server 會留著它」。

F153 的 frozen acceptance **一字未動**（改了就是竄改）；這份檔案是那句話的替代紀錄。
F153 本身仍是 `failing`：它的驗證方式要求「同一句指令分別經外部 Claude 與內建對話
產生相同資料列」，那需要一把真的 LLM key 與 Ryan 本人操作，headless session 做不到。
