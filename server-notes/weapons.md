# Оружие, попадания, урон

## Кто считает попадание 🔎
Клиент сам находит попадание и шлёт серверу точки, сервер возвращает урон.
- От стрелка (имена кодеков методов): `_fire_shooter`, `_fire_barrel`, `_fire_shotDirection`, `_fire_target`,
  `_fire_targetHitPoint(s)`, `_fire_staticHitPoint`, `_fire_targets`; `_tankHit_target`, `_tankHit_hitPointLocal`,
  `_tankHit_directionWorld`; `_staticHit_hitPoint`; `_hit_hits`, `_hit_origins`, `_hit_critical`;
  `_primaryShot_shotDirection`, `_shot_direction/_muzzle/_origin`, `_shootToPosition_*`, `_traceHit_hitTraceData`.
- От сервера: `_showDamageForShooter_damages`, `_primaryRemoteShot_*` (выстрел чужого танка), `_kill_damageType`,
  `_nextShotCriticalStatePerpared_critical` (крит решает сервер ❓).
- Снаряды-лучи: `raycastShell`, `raycastShellMovement`, `raycastShellCollisionFilter`, `raycastShellHitCounter`.
- Направление кодеков (клиент→сервер или наоборот) пока выведено по смыслу ❓, проверить по протоколу.

## Параметры (enum свойств, @7107538 и рядом) 🔎
`DISCHARGE_SPEED`, `FREEZE_PER_TICK`, `VERTICAL_ANGLES`, `DRONE_RELOAD…`, `ISIS_INCREASE/DECREASE_TARGET_TEMPERATURE_PER_TICK`,
`SHELL_GRAVITY_COEF`. Значения, судя по всему, приходят с сервера ❓.

## Параметры из данных моделей (CC) ✅ трафик
Числа пушек и корпусов сервер присылает в данных моделей объектов боя (`loadObjectsData`). Обучающий бой
(`captures/session1.decoded.jsonl`, пространство `2aaaaabafeae733d`, первые экземпляры):
- `WeaponWeakeningCC {maximumDamageRadius: 40, minimumDamagePercent: 25, minimumDamageRadius: 90, shotRange: 95}` —
  ослабление урона с расстоянием (единицы ❓, похоже на метры);
- `SimpleArmorCC {maxHealth: 2250}` — здоровье корпуса;
- `HullCommonCC` (звуки и цвет смерти), `EngineCC` (звуки двигателя), `DeferredOverdriveCC` (задержка
  овердрайва `delayMs: 2000`, звуки, свет).
Свойства для экрана гаража идут в `ItemPropertiesCC` (1227 из 1922 предметов пространства `05f6fe6e`).

## Выстрелы «Твинса» в трафике ✅ трафик, смысл 🔎
- `4c1dc500ead589a3(Int clientTimeMs, Byte ствол, Int номер выстрела, Vector3 направление)` — каждый выстрел;
  ствол чередуется 0/1, номер растёт с 1.
- `07c95e80167b2884(Int clientTimeMs, Int номер выстрела, Vector3 точка)` — снаряд попал в статику (стену, землю).
- `035ddeaca9d00907(Int, Int, GameObject цель, Vector3, Vector3)` — попадание в танк (в обучении по мишеням);
  сервер в ответ шлёт `showDamageForShooter`/`hit` (registration-to-tutorial.md).

## Пушки (модели) ✅
43 модели башен `.a3d`. Узлы: `turret`, `muzzle*` (точки вылета), `fmnt` (крепление к корпусу ❓),
`smk_*` (дым), `barrel*`. Корпус крепит башню в узле `mount`.

## TODO
- Найти структуру параметров каждой пушки (урон, перезарядка, дальность) и откуда она приходит.
