# Архитектура: клиент vs сервер

## Свой танк считает клиент 🔎
- Цикл с фиксированным шагом, этапы (enum-строки в бандле):
  `FIXED_TIME_STEP_BEFORE_PHYSICS`, `..._BEFORE_PHYSICS_CHASSIS`, `..._BEFORE_PHYSICS_CHASSIS_CONTROL`,
  `..._BEFORE_PHYSICS_SOARING_CHECKER`, `FIXED_TIME_STEP_AFTER_PHYSICS`, `..._AFTER_PHYSICS_TANK_COMPONENT`,
  `..._AFTER_PHYSICS_TURRET`, `..._AFTER_PHYSICS_TURRET_SERVER_INTERFACE`, `..._AFTER_PHYSICS_SOARING_CHECKER`.
  Порядок тика: управление → шасси → шаг физики → компоненты танка → башня → отправка состояния башни серверу.
- Длина тика задаётся сервером: `BattleLockingCC [clientTickPeriodMs = …]` (@6705044). В обучающем бою
  `clientTickPeriodMs = 300` ✅ (трафик: `loadObjectsData` пространства `2aaaaabafeae733d`). Что именно идёт
  с этим периодом ❓: состояние `51ab830176962b6d` клиент слал в среднем раз в 68 мс (physics.md).

## Синхронизация 🔎
- Отладочная панель «Tank net sync» (@8313302) считает `State commands sent` и `Control commands sent`:
  клиент шлёт серверу и физическое состояние, и управление. Есть счётчик отношения state/control.
- Режимы обновления танка (enum @7220226): `COMMON`, `STATE_CORRECTION`, `REMOTE_UPDATING`, `BOT`, `TUTORIAL`;
  танки `LOCAL` / `REMOTE`. Сервер может прислать коррекцию состояния; чужие танки обновляются по данным сервера.
- В enum-ах есть также `SYNCHRONIZED`, `rotationInterpolationFactor` (интерполяция поворота чужих танков ❓).

## Обучающий бой ✅ трафик (registration-to-tutorial.md)
- Ботов симулирует клиент: сервер шлёт им команды (`moveTo`, `moveBy`, `updateTurret`, `fire`), клиент считает
  их физику и присылает их состояние (`51ab830176962b6d`) и управление (`6852c2c4158e67ff`).
- Время: сервер раз в 2 с шлёт `313e2d3c89ad6cb1(Int serverTimeMs, Float)`, клиент отвечает
  `316c237866d0b2bf(Int clientTimeMs, Int serverTimeMs)`.

## Следствие для сервера ❓
Минимальный сервер может не повторять физику: принимать state/control от клиента, рассылать остальным,
при нарушениях слать `STATE_CORRECTION`. Урон и попадания считать на сервере (см. weapons.md).
