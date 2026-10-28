# Авторизация

Как устроено в клиенте общее: каждая «модель» (Kotlin-класс) имеет прокси `server` с методами. Метод кодирует
аргументы кодеками (`v().xb()` = String, `v().pb()` = Boolean ❓) и отправляет `new U(<id модели>, <id метода>, buffer)`.
Входящие вызовы сервера разбираются в `u7j(methodId, buffer)` (switch по ID метода). ID методов: 64-битные константы
(`new R(lo, hi)`) в конструкторе модели ❓ ещё не выписаны.

## 0. Рукопожатие протокола 🔎
Служебные команды (@3038837): `1` = «Hash request», `2` = «Hash response», `32` = «ClientLog».
После подключения клиент запрашивает хэш, сервер отвечает. Рядом лежит функция инициализации XOR-шифра потока
(два `Int32Array(8)`, ключ из полученных байт). ❓ точный порядок и формат, нужен захват трафика.

## 1. Вход по логину и паролю ✅ (код прочитан)
- Состояние UI `LoginByPasswordState(login, password, rememberMe, status, onlyLogin, incorrectLogin2FA, requestsNumber2FA)` (@614396).
- Модель входа по паролю (@1318074): по действию UI вызывает `server.nh6(login, password, rememberMe)`:
  String, String, Boolean. **Пароль уходит строкой как есть**, без хэширования на клиенте; защищён только
  транспортом (WSS + XOR протокола).
- Ответы сервера этой модели: `jh3` → экран «неверный пароль», `gh3` → переход на экран 2FA, `ih3` → флаг успеха ❓.
- 2FA: `server.eh4(code)` (код из `Login2FA(code=…)`).

## 2. Вход по сохранённому хэшу («Запомнить меня») ✅
- Сервер присылает `rememberUsersHash(hash)` (кодек `_rememberUsersHash_hashCodec`) → клиент кладёт в
  localStorage `entrance_hash_key` (@609595). Для 2FA: `remember2FaHash(hash)` → `two_fa_hash_key`.
- При следующем запуске: `LoginViaHash(hash)` → `server.nh7(hash)`; одноразовый вход `LoginViaSingleHash(hash)` →
  `server.oh7(hash)` (ключ `single_entrance_hash_key`) (@1266796).
- Если хэш не подошёл (`ch7`), клиент удаляет `entrance_hash_key` и `name-userHash` (@610087) и показывает форму.
- Прочие ключи localStorage: `invite_key`, `skip_start_screen`, `social_network_id`.

## 3. Прочие способы входа 🔎
- Соцсети OAuth: VK, Google, Apple (`RequestOAuthUriWithRedirect/NewWindow(socialNetworkId)`, сервер отвечает
  `_receiveOAuthUrl_url`, `SocialNetworkEntranceParams(clientId, enabled, snId)`).
- Партнёры: Steam (`authSessionTicket`), VK Play, китайский SDK (`ChinaSDKTokenLogin(token)`), `ClassicEarlyAccessLogin(token)`.
- Регистрация: `Entrance.Register`, `RegistrationModelCC`, ограничения пароля `SetPasswordRestrictions(min/maxPasswordLength,
  passwordNeedDigit/Lower/Upper)` присылает сервер.
- Капча: `CaptchaCC`, сервер шлёт `_showCaptcha_captcha/location`, `_captchaCorrect`, `_captchaFailed`; есть reCAPTCHA.
- Инвайты: `InviteEntranceCC(enabled)`, `_inviteAlreadyActivated_uid`.
- Привязка Twitch ✅ трафик (пространство магазина `05f6fdcf`, модель `48f37c2fea1d1493`):
  `{account: null, accountLinkingEnabled, daysForNextLinking, linkUrl}`. `linkUrl` — адрес OAuth Twitch с
  `redirect_uri` на `forumauth.eu.tankionline.com` и `state=<userId>%3A<40 hex>`: id пользователя и подпись
  сервера ❓. Это личные данные аккаунта: `tools/make_templates.py` убирает `state` из шаблонов.

## Экраны входа (enum) 🔎
`Entrance.SelectEntranceType`, `LoginByPassword`, `Login2FA`, `Register`, `Restore`, `SetPassword`, `ChangeUid`,
`Invite`, `LicenseAgreement`, `MigrationInForm/Out`, `NeedEnterByLogin`, `RegistrationForbidden`, `SetRealName`.

## Для своего сервера ❓
Минимум: ответить на Hash request, отдать модели экрана входа (Entrance, LoginByPassword) с выключенной капчей,
принять `nh6(login, password, remember)`, проверить по своей базе, прислать `rememberUsersHash` при remember=true,
дальше вести клиента в лобби. Капчу и соцсети можно не реализовывать (`captchaEnabled=false`, соцсети выключены).
