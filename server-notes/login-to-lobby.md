# От входа до главной сцены (по захвату session1, повторный вход) ✅

Лог: `captures/session1.log.txt` (строит `tools/ws_log.py`). Таблица ID: `server-notes/proto_ids.json`.
Времена ниже — секунды от начала захвата.

1. **Главный сокет** (без пространства): клиент → `HashRequest` (параметры запуска: resources, config-template,
   balancer, lang, browser_user_agent, device_type, client_version, …); сервер → `HashResponse` (hash[32] + флаг шифра)
   и сразу `OpenSpace(spaceId=05f691cc)`.
2. **Пространство входа 05f691cc**: клиент открывает новый сокет, `OpenSpaceConnect(hash, spaceId)`.
   - сервер → `loadDependencies` (классы/ресурсы, 1,7 КБ), клиент → ack `ca5814` (i32 1), сервер → `loadObjectsData`.
   - экран выбора входа, регистрация: клиент шлёт ник по буквам, сервер отвечает `enteredUidIsBusy` с вариантами ников.
   - вход: клиент → `model_17ec32.4d6d3a(login, password, remember)` (414–417 с), сервер → `rememberUsersHash(hash)`.
3. Сразу после входа сервер по главному сокету шлёт серию `OpenSpace(spaceId)`, клиент на каждое открывает сокет:
   | spaceId | что приходит |
   |---|---|
   | d634b693fb | системное: `initializeProBattleRewardLimit`, `sendWarnMessage` |
   | 05f7b228 | лобби/режимы: `loadDependencies` 3,7 КБ, потом `endLayoutSwitch`, `sendData` |
   | 05f6fdcf | гараж/магазин: `loadDependencies` 42 КБ, `loadObjectsData` 45 КБ; клиент сразу запрашивает `tips`, `announcements` |
   | 05f69398 | чат: `showMessages` (20 КБ, общий канал GENERAL) |
4. `endLayoutSwitch` в 05f7b228 (420,16 с) → клиент показывает `Lobby.Home`: **это и есть главная сцена**.
   От отправки пароля до главной сцены прошло ~3 с и 4 пространства.

## Переход вход → лобби ✅ (проверено повтором `tools/replay_server.py`, 2026-10-27)
- После `rememberUsersHash` и ответа клиента `…18c358` сервер **закрывает сокет пространства входа** 05f691cc
  (в захвате `closed` в 417,35 с, одновременно с `OpenSpace(d634b693fb)`). Без этого клиент остаётся на форме входа.
- Закрытие входа переводит клиент на экран `System.Loader`. Обработчик `endLayoutSwitch(origin, state)` (@1327594)
  открывает лобби только если текущий экран `System.Loader`; иначе пакет молча игнорируется.
- Один пакет несёт несколько команд. В пространстве лобби 05f7b228 первый пакет: `loadDependencies` +
  `loadObjectsData` + `beginLayoutSwitch` + `sendData` + `setOnline`/`setRank`/`setUid`; `endLayoutSwitch` — отдельно.
  В чате 05f69398: `loadDependencies` + `loadObjectsData`.
- `loadDependencies`: первое i32 — номер колбэка ✅ по трафику. 1 → клиент отвечает ack `19368b1c6aca5814(1)`
  (вход, d634b693fb, гараж); 0 → ответа нет (лобби, чат).
- `beginLayoutSwitch(state:i32)` = `6bde6cf328643d9b`, `endLayoutSwitch(origin:i32, state:i32)` = `7e7ef0afa90578e9`.
  Значения state — enum, имена из схемы ✅: 3 `BATTLE`, 0 `MATCHMAKING` (лобби), 2 `GARAGE`.
  Клиент сам просит смену экрана `5567de(state)` (после обучения — `MATCHMAKING`).
- Чат: как только объект чата загружен и лобби показано, клиент шлёт `changeChannel(channel:String)` =
  `5cc0f95f8d83211b` (событие `ChangeChannelOnServer`, @272716 / @1312202), сервер отвечает `showMessages`.
  В захвате все 6 вызовов несут `"GENERAL"` ✅ (схема и `captures/session1.decoded.jsonl`; раньше здесь ошибочно
  стоял i64 — 8 байт тела оказались байтом длины и 7 символами).
- Имена экранов клиента — синглтоны со строками (`Entrance.LoginByPassword`, `System.Loader`, `Lobby.Home` …, @341186).

## Что нужно серверу для главной сцены
- Отдать те же `loadDependencies`/`loadObjectsData` для 4–5 пространств. Для сервера-повторителя можно
  отправлять их байты из захвата как есть (шифр можно выключить флагом 0 в HashResponse) ✅.
- Закрыть сокет пространства входа после успешного входа, затем `endLayoutSwitch(0, 0)` в лобби ✅.
- Корректно ответить на ack `ca5814` и запросы `tips`/`announcements`.
- ✅ Формат `loadDependencies` / `loadObjectsData` разобран (protocol-codecs.md): их можно собирать кодеком
  `tools/proto_codec.py`; проверено в клиенте (`replay_server.py --patch`, ник и кристаллы изменены).

⚠️ Лог и захват содержат логин/пароль тестового аккаунта открытым текстом — не публиковать.
