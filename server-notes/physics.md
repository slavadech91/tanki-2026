# Физика танка

## Состояние тела 🔎
Позиция, скорость (`velocity`), угловая скорость (`angularVelocity`), поворот (кватернион). Клиент проверяет
состояние на NaN: «Invalid current/previous physics state: position, velocity, angularVelocity, rotation» (@7378377).
Хранится текущее и предыдущее состояние (для интерполяции рендера между тиками ❓).
Связанные имена: `tankPhysics`, `tankPhysicsComponent`, `physicsComponent`, `fillPhysicsState`,
`updatePhysicsState`, `setPhysicsTransform`. Кодеки: `codec_linearVelocity`, `codec_angularVelocity`.

## Состояние танка в сети: `TankState` ✅ (кодек `T5` @7941054, чтение `j5` @7196040, запись `S5`/`C5` @7196162)
23 байта, битовый поток MSB-first, 4 вектора × 3 компоненты (x, y, z), по порядку:
| поле | бит | масштаб | диапазон |
|---|---|---|---|
| position | 19 | 0.25 | ±65536 |
| orientation | 13 | 0.0007669904 (= 2π/8192) | ±π (углы, рад) |
| linearVelocity | 13 | 1 | ±4096 |
| angularVelocity | 13 | 0.005 | ±20.48 |
- Чтение: `value = (bits − 2^(n−1)) · scale`. Остальные 10 бит из 184 нулевые.
- Запись (клиент): `e = roundToInt(v / scale)` (Math.round), `s = min(2^(n−1), e < −2^(n−1) ? 0 : e − 2^(n−1))`,
  пишутся младшие `n` бит `s`. В диапазоне это `bits = e + 2^(n−1)`; за верхней границей значения заворачиваются.
- Где: сервер → клиент `setState(TankState)` `513e03aef8d44344` (модель танка `M[kill,push]`);
  клиент → сервер `44eb92059fda7def(i32, i16, TankState)` (та же модель) и `51ab830176962b6d(i32, TankState)`
  (модель `M[setActive]`).
- По обучающему бою (`captures/session1.decoded.jsonl`, сокет 18384.11000) ✅ трафик, смысл 🔎:
  - значения правдоподобны: после появления танк падает — z 582 → 385 при `linearVelocity.z = −437`, углы
    в радианах малы; **ось Z вверх**, координаты карты порядка тысяч единиц;
  - `44eb92059fda7def(i32, i16, TankState)` — состояние **своего** танка (объект `…feae733a`), 129 раз,
    медиана 0,4 с;
  - `51ab830176962b6d(i32, TankState)` — состояние **ботов**: 268 раз по 7 объектам танков ботов (медиана 68 мс
    по всем вместе). В обучении физику ботов считает клиент и отчитывается серверу
    (registration-to-tutorial.md) ✅ трафик;
  - i16 — номер появления ✅: 1 до второго появления, 2 после (то же число клиент шлёт в `81c733`, сервер — последним
    аргументом `spawn`); так же во втором аргументе `updateTurret` `711e4f0028314036(i32, i16, i32)`;
  - i32 — время клиента в мс 🔎: растёт как часы (7101 → 7728 за 0,62 с), ноль примерно в момент загрузки объектов
    боя; со временем сервера из синхронизации (`ad6cb1`) не совпадает.
  - `setState` от сервера в захвате не встречался: ботов обучения двигает сам клиент.

## Мир 🔎
- `MapParams(gravity, bounds, dustSettings, ambientColor, lightColor, lightIntensity, lightDirection,
  useFog, fogStart, fogEnd, fogColor, fogAlpha)` (@7991515): гравитация задаётся картой.
- Геометрия столкновений: `codec_collisionGeometry`, `codec_collisionGeometryOutsideGamingZone`,
  `codec_detailedCollisionGeometry`, `collisionDetector`, `detailedCollisionDetector`.
- Танк: `codec_collisionBoxes`, `codec_mainCollisionBox`, `staticCollisionBoxes`. В моделях `.a3d`
  этому соответствуют узлы `BoundBox` и 24-вершинные `BoxNN`.

## Гусеничное шасси 🔎
- `TrackedChassisParams(damping)` (@8249664), `TrackedChassisControlState(moveForwardSpeed, turnLeftSpeed,
  reverseBackTurn)` (@8247186), `TrackedChassisCC`, `TrackedChassisControl`.
- Лучи: `numRaysUp`, `numRaysDown`, `auxRaysOrigins` (подвеска лучами ❓).
- Визуал: `leftTrackTexToWorldRatio`, `rightTrackTexToWorldRatio`, `codec_trackAnchors`.

## Ховер-шасси 🔎
`HoverChassisParams(tiltMoveMaxAngle, tiltMoveScale, tiltStabilityMaxAngle, tiltStabilityScale,
optimalSurfaceDistance, enginesPosition, enginesProportionalFactor, enginesIntegralFactor,
enginesDifferentialFactor, isMoveCameraRelative, maxControllableAngle)` (@8234838): высоту держит ПИД-регулятор.
`HoverChassisControlState(forwardSpeed, …)`.

## Прочее 🔎
- `SOARING_CHECKER`: проверка «парения» в воздухе (античит/антизастревание ❓).
- `tankMovementChecker`, `TankMovementStage`, `INSTANT_MOVE`, `MovementTrajectory`.
- Снаряды: `SHELL_GRAVITY_COEF`, `GrenadeParams(gravityFactor, …)`.

## TODO
- Найти функцию шага гусеничного шасси: силы, трение, подвеска, константы.
- Где берутся числа (масса, скорость, ускорение): с сервера в параметрах танка ❓
