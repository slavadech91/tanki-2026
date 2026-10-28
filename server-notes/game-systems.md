# Игровые системы

## Режимы боя 🔎
Enum (@1733894): `QUICK_BATTLE`, `DM_ONLY`, `TDM_ONLY`, `CTF_ONLY`, `CP_ONLY`, `SGE_ONLY`, `AS_ONLY`, `RUGBY_ONLY`,
`TJR_ONLY`, `JGR_ONLY`, `HOLIDAY`. Флаги: `_dropFlag_position`, `_returnFlagToBase_tank`; точки:
`_setPointState_state`, `_onPointActiveStateChanged_*`.

## Спавн 🔎
`_prepareToSpawn_position/orientation`, `_spawn_position/orientation/team`, `_tankPreparingToSpawn_tank`, `_teleport_position`.

## Бонусы, мины, прочее 🔎
`_spawnBonuses_spawnData`, `_spawnBonusesOnGround_spawnData`, `_removeBonuses_bonusIds`, `BonusCollisionEvent`,
`_removeMines_mineIds`, `_spawnMeteor_*`, `MeteorDescriptor(groundPosition, upperPosition)`.

## Гараж 🔎
`_buildTank_parts/partsInfo/paints/paintsInfo/kode`; `GarageRemoveItemFromDepot`, `GarageRemoveDevice`, …

## Дроны, ульты 🔎
Свойства `DRONE_POWER_BOOST`, `DRONE_POWER_DURATION`, `DRONE_CRITICAL_HEALTH`, …; `_showUltimateUsed_*`.
Корпуса в enum (@7221671): `HUD`?, `ARES`, `JUGGERNAUT`, `MAMMOTH`, `CRUSADER`, … ❓ проверить полный список.
