# Мастерская Blender для DRONEWORKS

Рабочая копия для подготовки моделей. Согласованные FBX из мастерской передаются в `DroneGame/Assets/_Project/Models/`. Решения по организации работы и проверкам описаны в [EGM-разборе](../blender-environment-egm-review.md).

## Где что лежит

| Папка или файл | Содержимое |
| --- | --- |
| [References](../References/) | 11 исходных изображений. Пресс, конвейер и квадрокоптер показывают форму и подвижные части. Листы рабочего и грузовика дают несколько ракурсов. Раскадровки показывают читаемость форм и цвета от первого лица. |
| [ArtSource/Blender](../ArtSource/Blender/) | `DRONEWORKS.blend` — пустой шаблон с метрическими единицами, коллекциями `EXPORT` и `REFERENCES`, материалом `DRONEWORKS_Palette` с фильтром Closest. |
| `ArtSource/Blender/Models/<имя>/` | Один основной `.blend` на модель, её скрипт bpy при наличии, дополнительные чертежи и принятые версии. Имена моделей и объектов бери из ART_SPEC. |
| [ArtSource/Textures](../ArtSource/Textures/) | Рабочая копия игровой палитры `T_Palette_DRONEWORKS.png`. Обновляй её из DroneGame при изменении палитры в игре. |
| `Exports/Unity/` | Передаваемые FBX. После импорта готовый FBX и его `.meta` хранятся в игровом репозитории. |
| `.local/` | Переносимый Blender, Bun и Studio, настройки и результаты под `.local/checks/`. |

[ART_SPEC](ART_SPEC.md) и [ART_STYLE](ART_STYLE.md) перенесены из DroneGame. Перед работой с игровыми заглушками сверь их с текущей игровой веткой. В мастерской подготовлены правила Git LFS для `.blend` и `.fbx` и исключения для локальной среды, резервов Blender и каталога передачи. Версии рабочих `.blend` до подключения Git сохраняй под отдельными именами внутри папки модели.

## Команды из корня мастерской

```powershell
.\Tools\Blender\blender.ps1 -Mode version
.\Tools\Blender\blender.ps1 -Mode open
.\Tools\Blender\blender.ps1 -Mode check
.\Tools\Blender\blender.ps1 -Mode export -Source '<путь к .blend>' -Output '<путь к .fbx>'
```

Команды можно запускать из `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <путь-к-blender.ps1>`, если политика запуска блокирует прямой вызов. Чтобы выбрать другой Blender, укажи `-BlenderPath` или задай `BLENDER_EXECUTABLE`. Если переносимой установки нет, распакуй [проверенный Windows x64 ZIP](https://download.blender.org/release/Blender5.2/blender-5.2.4-windows-x64.zip) под `.local/`. Сверь SHA-256 по [файлу релиза](https://download.blender.org/release/Blender5.2/blender-5.2.4.sha256).

При сохранении копии шаблона в папку модели включи **Remap Relative Paths**. Добавляй подложки в `REFERENCES` и калибруй по размеру из ART_SPEC. Меши в `EXPORT` получают имя и origin по спецификации. Сохраняй локальное положение дочерних деталей при применении Rotation & Scale.

Экспорт жёстких моделей берёт меши из `EXPORT` с настройками **−Z Forward, Y Up, FBX Units Scale, Apply Transform**. Используй профиль, прошедший [приёмку FBX в Unity](#приёмка-fbx-в-unity). Для конвейера уже проверен свой режим `export-unity` с коррекцией V и Bake Axis Conversion при импорте. [Команда и результаты конвейера](../ArtSource/Blender/Models/ConveyorSegment/final_report.md#fbx-и-проверка-в-unity)

## Приёмка FBX в Unity

Проверка покрывает жёсткие модели `SM_*.fbx`. Для скелетов и анимаций нужен отдельный прогон. Для пробника примени Rotation & Scale, задай origins и сохрани локальное положение дочерней детали. Применение Location сместит origin, поэтому для пробника используется это временное исключение из пункта All Transforms в ART_SPEC. После успешного прогона зафиксируй проверенный порядок в ART_SPEC и этой инструкции. [Blender Manual — Apply](https://docs.blender.org/manual/en/latest/scene_layout/object/editing/apply.html)

1. Получи `SM_BlenderProbe.fbx` командой `blender.ps1 -Mode check`. Она использует тот же профиль FBX, что и `-Mode export`. Импортируй пробник в `Assets/_Project/Models/_BlenderProbe/` изолированной копии проекта и помести его в пустую сцену Unity `6000.3.28f1`.
2. В Unity установи Scale Factor **1**, Convert Units **вкл.**, Preserve Hierarchy **вкл.** Для пары Blender Apply Transform / Unity Bake Axis Conversion начни с «вкл. / выкл.». При расхождении проверь «вкл. / вкл.», «выкл. / вкл.», «выкл. / выкл.» в этом порядке. Для экспорта с выключенным Apply Transform используй `-NoApplyTransform`. Зафиксируй первый профиль, прошедший всю таблицу. Если все сочетания дают расхождение, запиши замеры и оставь приёмку открытой. [Unity 6.3 — Model Import Settings](https://docs.unity.com/en-us/engine/6000.3/manual/assets-and-media/asset-types/models/importing/fbximporter-model)
3. Для проверки цвета назначь временный материал `Universal Render Pipeline/Unlit` с общей палитрой, белым цветом, масштабом UV 1 и сдвигом 0. Проверь настройки импорта PNG — Point, Clamp, mipmaps и сжатие выключены.

| Контроль | Ожидание |
| --- | --- |
| Состав и ориентация | Иерархия мешей `Frame > Belt`. Передняя метка на геометрии `Belt` находится у переднего конца по −Y в Blender и +Z в Unity. Метка смещена к стороне +X, чтобы обнаружить зеркалирование. Камера, свет, подложка и контрольный меш `OutsideExport` находятся вне `EXPORT`. Импорт содержит только ожидаемые меши и их иерархию, без коллайдеров. |
| Габариты и опора | При нулевых позиции и вращении экземпляра и масштабе 1 объединённые bounds мешей по оси X/Y/Z составляют `1,20 × 2,00 × 0,75 м` в Blender и `1,20 × 0,75 × 2,00 м` в Unity. Origin `Frame` в `(0; 0; 0)` по центру основания. Нижняя грань в Unity на `Y = 0`. Допуск по позициям и габаритам ±1 мм. |
| Дочерний pivot | Цель для `Belt` относительно `Frame` в Unity `(+0,30; +0,60; +0,65) м`, в координатах шаблона Blender `(+0,30; −0,65; +0,60) м`. Проверить обе позиции и повернуть импортированный `Belt` вокруг его локальной X на 90°. Pivot остаётся на месте, а метка смещается вокруг него. Проверку вращения проводить после измерения габаритов. |
| UV и материал | `Frame` использует STEEL `#585D7F`, UV `(0,1875; 0,9375)`. `Belt` использует SIGNAL `#F2A608`, UV `(0,6875; 0,9375)`. Проверить соответствие отдельных поверхностей двум ячейкам через назначенный в Unity материал. Автосоздание Unity-материала из FBX за пределами этой проверки. |

Сохрани замеры, профиль импорта, скриншот и журнал Unity рядом с результатами Blender в `.local/checks/<run-id>/`. Перед сдачей проверь через `git status`, что временный FBX и его `.meta` отсутствуют в изменениях игровой ветки.

## Инструменты агента

[Обзор скиллов, MCP и готовых ассетов для DRONEWORKS](BLENDER_TOOLS.md).

| Инструмент | Где пригодится |
| --- | --- |
| [Blender CLI и bpy](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html) | Повторяемая сборка, контроль размеров, пакетный экспорт и рендер. Проектные команды используют этот путь. |
| [Blender Agent Studio](https://github.com/ifBars/blender-agent-studio) | Инспекция сохранённых сцен, превью и фиксированные ракурсы. Семь знакомых скиллов для работы с референсами, моделирования, проверок и рендера установлены в `.agents/skills/`. |
| [Blender Lab MCP](https://www.blender.org/lab/mcp-server/) и [MCP for Blender от ahujasid](https://github.com/ahujasid/mcp-for-blender) | Варианты для живой сессии Blender. Имеет смысл отдельно испытать, если для этапа понадобится вмешиваться в открытую сцену и следить за viewport. |

### Контрольные суммы MCP

Studio установлена из коммита `6ff97fad06d09f5885c941e0bbf3a8f429da3560`, Bun — 1.3.5. Лицензия скиллов — [MIT](BLENDER_AGENT_STUDIO_LICENSE.txt). Для переноса распакуй каталог `plugins/blender-agent-studio` из этой ревизии под `.local/studio/` и положи рядом переносимый `bun.exe`. Сверь SHA-256, затем из каталога плагина запусти `bun install --frozen-lockfile`. Точка входа MCP — `bun .\mcp\server.ts` из того же каталога.

| Файл относительно `.local/studio/` | SHA-256 |
| --- | --- |
| `plugins/blender-agent-studio/bun.lock` | `CF11DB8DD25179D6F94773A6E3754E6FB34AFB3C661EBECFBCAB5837C521480A` |
| `bun.exe` | `0025A8BC31F136745D102212DDB192A1876C721B71DEEB43123D18375FCF030C` |

Сервер `blender_workshop` указан в [проектной конфигурации](../.codex/config.toml). После перемещения мастерской обнови путь к launcher в конфиге. Убедись, что Codex загружает конфигурацию этой папки, и вызови `blender_check_setup`. Независимая проверка канала stdio из корня мастерской:

```powershell
.\.local\studio\bun.exe .\Tools\Blender\check-mcp.ts .\.local\checks\mcp-repeat
```

На Windows при запуске проверки из ограниченной оболочки Bun может получить `EPERM` при старте дочерних процессов. Прогон от 19 ноября прошёл в обычном контексте пользователя.

## Проверка от 19 ноября 2026

| Проверка | Результат |
| --- | --- |
| Blender 5.2.4 LTS, сборка `cd5dc428cce1` | Получен официальный ZIP с проверкой SHA-256. Окно открылось с шаблоном и ответило на сообщение Windows. Фоновый bpy вернул заданный код 33 при контрольной ошибке. [Окно](../.local/checks/blender-gui.json) |
| Шаблон и экспорт | Копия шаблона по пути с кириллицей и пробелом открылась, палитра и подложка загрузились после Save As во вложенную папку. Cycles CPU отрендерил превью. После обратного импорта FBX в Blender совпали имена, иерархия, габариты, ориентация, pivot и UV. Отдельная команда экспорта также прошла. [Замеры](../.local/checks/setup-02/report.json), [превью](../.local/checks/setup-02/preview.png), [FBX](../.local/checks/setup-02/SM_BlenderProbe.fbx) |
| MCP stdio | Сервер зарегистрировал 19 инструментов. `blender_check_setup` вернул `pass` и PNG, проверки Cycles CPU и EEVEE прошли. [Отчёт](../.local/checks/mcp-02/mcp-stdio.json) |
| MCP через Codex | App-server Codex из каталога мастерской загрузил проектный сервер и вызвал `blender_check_setup` в одноразовой сессии. В ответе `pass` и PNG. [Отчёт](../.local/checks/codex-native-01/codex-native.json), [превью](../.local/checks/codex-native-01/preview-0.png) |
| Git LFS | Локальный репозиторий `main` создан. `git check-attr` подтвердил LFS для `.blend` и `.fbx`, `git check-ignore` подтвердил исключения. Первый коммит и удалённый репозиторий ещё не заведены. |
| Unity | Редактор `6000.3.28f1` не найден в проверенных установках. Проверка масштаба, осей, вращения дочерней детали и палитры в Unity остаётся открытой. |

Первый шаг по D2 — блокинг сегмента конвейера по ART_SPEC. После проверки силуэта и габаритов стыкуй два сегмента, проверяй `Belt`, материал стрелок и прокрутку UV в обе стороны перед заменой заглушки. [План DroneGame](../../DroneGame/Docs/ROADMAP.md)
