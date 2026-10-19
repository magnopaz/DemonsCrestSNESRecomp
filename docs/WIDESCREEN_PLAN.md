# Plano — widescreen em Demon's Crest

Este documento planeja a adição de widescreen ao port de **Demon's Crest (USA)**
tomando como referência o que foi feito no **MegaManXSNESRecomp**. O plano é
baseado em leitura direta do ROM (`M:\Opencode\roms\Demon's Crest (USA).sfc`),
do framework `snesrecomp` (pin `eb75c88`), e do código de MMX
(`src/mmx_renderer.c`, `src/mmx_wide_policy.c`, `src/mods/mmx_widescreen_plugin.c`,
`tools/apply_overrides.py`, `mods/preloaded/packages/megaman-x.enhancement.widescreen`).

---

## 0. Resumo executivo

1. O MMX foi lançado com widescreen em **duas trilhas**: hooks no C gerado
   (cull/spawn/OAM) + o *renderer* custom para compor as margens. O framework
   já possui a infraestrutura necessária (`PpuSetExtraSpace`, políticas por
   camada, `WsShadow`, *line enhancer*, `SnesDisplayAspect`) e os ports X2/X3
   usam a **trilha nativa** (sem compositor próprio).
2. Demon's Crest é **Mode 1** com BG1/BG2 de 64×32 (16 cores) e BG3 (4 cores)
   para o HUD superior-esquerdo. Câmera, scroll por camada, pipeline de
   streaming de tilemap, loop de objetos, cull, emissor de OAM e spawn de sala
   já foram localizados no ROM (tabela §3.7).
3. **Decisão proposta:** seguir a trilha nativa (`native_widescreen = 1`) com
   um pequeno módulo específico (`dc_widescreen.c`) que publica políticas por
   frame, um cache host-side do mapa de metatiles da sala (somente leitura) e,
   se necessário, um *line enhancer* próprio. O compositor custom do X1 fica
   como **contingência** (Fase 8), com critérios objetivos de acionamento.
4. Tudo entra atrás de um mod default-off (`demons-crest.enhancement.widescreen`),
   espelhando o manifesto do MMX, com opções de aspecto Adaptive/16:9/21:9/32:9
   e kill-switches (`SNESRECOMP_WS_SPAWN`, `SNESRECOMP_WS_STAGE`) para bisseção.
5. Pré-requisito real: o port precisa chegar ao marco "jogável" (hoje é apenas
   scaffold — `src/game_rtl.c` é o *beam frame driver* sem lógica de título).
   A **Fase 1 é inerte e pode ser feita já**; as Fases 2+ exigem o jogo rodando.

### 0.1 Estado da implementação

Implementado (2026-10-18):

| Arquivo | Estado |
|---|---|
| `mods/preloaded/packages/demons-crest.enhancement.widescreen/1.0.0/manifest.toml` | pacote completo (feature + opção `aspect` + plugin), validado contra o parser do runtime |
| `src/mods/dc_widescreen_plugin.c` | ativação/reset, lê a opção de aspecto |
| `src/dc_display.c/.h` | largura/aspecto/clamp (`kPpuBufWidth`), janela, viewport |
| `src/dc_widescreen.c/.h` | política por frame: pillarbox fora de gameplay, BG3 clampada em gameplay; costuras das Fases 3/6 marcadas |
| `src/main.c` | `widescreen_supported`, `native_widescreen`, `prepare_frame`, `begin_sim_frame`, `end_sim_frame`, janela |
| `CMakeLists.txt` | fontes adicionadas ao alvo |

Verificação feita: os três arquivos `.c` novos e `main.c` passam por
`zig cc -std=c11 -Wall -Wextra` (com stubs SDL-free dos headers do framework);
o `manifest.toml` parseia e cumpre as validações do `mod_runtime.cpp`.

Ainda pendente (exige build completo e/ou port jogável): provar o gate `$8D`
com watchpoints (Fase 2), `tools/dc_apply_widescreen_hooks.py` e as Fases 3–8.

### 0.2 Validação de build (2026-10-18)

Toolchain montado nesta máquina: GCC 16.2 (MinGW-w64 UCRT/MSVCRT POSIX, via
winget `BrechtSanders.WinLibs.POSIX.MSVCRT`), Ninja (pip), CMake, Rust 1.97.1
(`x86_64-pc-windows-gnu`, linker = o gcc do MinGW) e SDL2 2.32.6 em `M:\SDL`
(`-DSNESRECOMP_SDL_BACKEND=SDL2 -DSDL2_DIR=M:/SDL/SDL2-2.32.6/x86_64-w64-mingw32/lib/cmake/SDL2`).
O analisador nativo foi construído de `snesrecomp/recompiler-rs`; regen = 463
roots → 4.535 variantes AOT, 112 TUs geradas; exe de 23,6 MB.

| Teste | Resultado |
|---|---|
| Mod off | screenshot 256×224, idêntico ao baseline |
| 16:9 / 21:9 / 32:9 | 342×224 / 448×224 / 682×224 (extra 43/96/213) |
| Pillarbox (frames 500, 3000, 24000) | centro 256px **0 pixels de diferença** vs. 4:3; margens pretas |
| Mode 7 (frame 12000) | centro idêntico; margens estendem o plano Mode 7 (correto — o Mode 7 ignora o clamp por design) |
| Estado guest (24000) | WRAM/VRAM/OAM/CGRAM **byte-idênticos** entre mod on/off |
| Determinismo | duas execuções on/off → screenshots idênticos |

Notas da validação: comparar capturas com `turbo on` inclui o OSD de turbo do
host no topo-esquerdo (não é conteúdo do jogo); usar runs sem turbo para
diffs. A sonda de cena mostrou `$8D = 0` no título/menus (24000), `>= 0x80`
nas cenas de história/demo (5000–20000) e nenhuma área 1..0x7F sem input — o
gate atual pilarboxa as cenas `>= 0x80`; decidir na Fase 3 se elas passam a
alargar (as margens delas também são tilemaps streamados).

Um `tools/play.ps1` (regen + configure + build + launch) foi adicionado para
repetir esse fluxo nesta máquina.

### 0.4 Fase 3 implementada: histórico de margens (2026-10-18)

O "framebuffer maior" que o jogo precisa não é VRAM (o convidado transmite uma
janela de 64x32 tiles/512px): é o store world-keyed do framework
(`snes/ws_shadow.c`, 4096x512 tiles), alimentado (a) pela varredura da
viewport nativa a cada frame e (b) **pelos próprios uploads de VRAM do jogo no
momento da escrita** (`WsShadowOnVramWrite`) — então o conteúdo que o jogo
prepara à frente da câmera entra no histórico assim que é escrito.

Implementação em `src/dc_widescreen.c`:

- `DcRegisterLayerHistory(0/1)`: BG1 com origem de mundo = câmera `$C0/$C4`
  (16 bits), BG2 com `$C2/$C6`; scroll de fase vem do PPU (`hScroll/vScroll`).
- **Sem `retainHistory`**: chaves de linha de mundo, o mesmo espaço da captura
  de escrita. Com `retainHistory` o serve lê linhas de viewport e a captura de
  escrita grava linhas de mundo — os uploads à frente nunca eram lidos
  (medido: leste com 14% de acerto; com chaves de mundo: **85–87%**; oeste
  **99,9%**).
- `WsShadowFrame` no `end_sim_frame` (`DcWidescreenAfterRaster`).
- Kill-switches de diagnóstico: `SNESRECOMP_WS_HISTORY=0` (volta à VRAM crua)
  e `SNESRECOMP_WS_STATS=1` (contadores hit/miss/raw a cada 600 frames).

**Patch local do framework necessário**: `WsShadowTile` servia chunks que
atravessam a borda nativa do histórico, e o streamer do DC atualiza colunas
assim que elas chegam à borda nativa — o resultado era alteração das colunas
nativas x=0..5 e x=251..255. O guard foi restringido a chunks **totalmente
fora** dos 256px (`snesrecomp/runner/src/snes/ws_shadow.c`), o que restaura a
identidade bit a bit do centro (verificado: 0 diffs em 23 frames da caminhada)
ao custo de, no máximo, um tile de costura dentro da margem. Esse patch precisa
subir para o framework; um `git submodule update` o reverte.

Validação: caminhada da fase 1 (câmera 0→1765), 23 frames largos — centro
bit-idêntico ao 4:3; borda traseira servida pelo histórico (99,9%) sem o eco
duplicado (ex.: a lâmpada que aparecia duas vezes); borda dianteira 85–87%
servida pelo conteúdo já escrito pelo jogo.

**Porém (2026-10-18, teste do dono + verificação com ground truth)**: as
chaves de mundo do store **não correspondem à janela real do tilemap do DC**.
Comparando a margem de um frame com a mesma região de mundo quando ela vira
nativa 256px depois (frame buffer como oráculo): a margem oeste difere em
~65% dos pixels e a leste em ~78% — o store é autoconsistente, mas mostra a
**seção errada** do cenário. O modelo do framework assume uma janela em anel
ancorada no scroll de pixel (map_col = world_tile mod 64); o streamer do DC
(provavelmente com scrolls por linha via HDMA) não satisfaz isso — nenhum
deslocamento constante alinha as duas amostras. Por isso o dono vê a área
adicionada "não se comportar como o resto" no scrolling.

**Decisão**: histórico **desligado por padrão** até derivar a regra da janela
(`SNESRECOMP_WS_HISTORY=1` reativa para experimentos). Sem ele, as margens
usam a VRAM transmitida: movimento idêntico ao resto da tela, com o eco na
borda traseira (o problema original). Próximo passo: derivar a regra da
janela (dumps em deslocamentos conhecidos, por linha) e então corrigir as
chaves ou implementar um resolvedor de margem por linha (line enhancer).

### 0.3 Rota de gameplay, gate e cobertura (2026-10-18)

`scripts/routes/gameplay.script` chega ao primeiro trecho jogável da fase 1:
título (frame ~24000) → Start (novo jogo) → ~20000 frames de salas de
cutscene (`$8D = 0xA0 + sala`) → **área 2** (motor de fase) no frame 43659,
ancorado por `until 008D == 02`.

Semântica de `$8D` confirmada na prática:

| `$8D` | Cena |
|---|---|
| 0 | boot / título |
| 1..0x7F | motor de fase (gameplay) — ramo do construtor de HUD em `$80:C948` |
| >= 0x80 | salas de cutscene/intro (dispatcher `$80:AF54`: `area = 0xA0 + (sala & 0x7F)`) |

O gate implementado (`1..0x7F`) está correto. No gameplay (área 2):
23 frames largos capturados ao longo da caminhada (câmera 0→1765) têm o
**centro bit-idêntico** ao 4:3 e margens válidas — a página de VRAM de 512px
cobre os ±43px neste trecho. A Fase 3 continua necessária para as
re-transmissões de limite de página e para as demais fases.

Cobertura: capturas do attract e do gameplay foram fundidas em
`recomp/tier2_coverage.json` (1023 linhas) com o novo `tools/merge_coverage.py`
(o baseline antigo é o registro persistente dos seeds: código já AOT não
reaparece como fallback). Regen: **484 roots / 4.935 variantes AOT** (antes
463 / 4.535). Rebuild e revalidação: rota determinística (WRAM idêntica entre
execuções em `stage_start`/`stage_600`), attract e gameplay sem stall.

---

## 1. Estado atual do port

| Item | Estado |
|---|---|
| Boot até intro | validado (rota `scripts/routes/attract.script`, 24.000 frames) |
| AOT rico | 463 roots / 4.535 variantes (rota capturada) |
| Scheduler | família `$81xx` pinada em LLE (`recomp/symbols.toml`) |
| Renderer | 100% do framework; `game_rtl.c` só chama o beam driver |
| Mods | catálogo vazio em `mods/preloaded/packages/`; loader já ligado no CMake |
| Widescreen | nada implementado; `main.c` não expõe `widescreen_supported` nem `native_widescreen` |

Arquivos que o plano toca:

```
CMakeLists.txt
src/main.c
src/game_rtl.c
src/dc_display.c/.h          (novo)
src/dc_widescreen.c/.h       (novo)
src/mods/dc_widescreen_plugin.c (novo)
mods/preloaded/packages/demons-crest.enhancement.widescreen/1.0.0/manifest.toml (novo)
tools/dc_apply_widescreen_hooks.py (novo)
docs/WIDESCREEN_PLAN.md      (este documento)
```

---

## 2. O que foi feito no Mega Man X

### 2.1 Infraestrutura do framework (reutilizável por qualquer título)

- **`runner/src/snes/ppu.h`** — superfície widescreen do PPU:
  - `PpuSetExtraSpace` / `PpuSetExtraSideSpace` (orla simétrica ou assimétrica);
  - `PpuSetWidescreenLayerClamp` (mantém camada nos 256px nativos);
  - `PpuSetWidescreenHudSplit`, `PpuSetWsHudOamShift(Range2)`, `PpuSetWsHudOamBand`
    (HUD BG3 em três blocos / sprites de HUD ancorados nas bordas);
  - `PpuSetWidescreenLayerMirror/Repeat/StretchBand/AnchorBand/ElasticBand`
    (por linha: repetir, espelhar, esticar, ancorar ou mapear por segmentos);
  - `PpuSetWidescreenLayerWorldMirrorBand` (reflete sobre as bordas do mundo
    autorado, não da viewport — arenas limitadas);
  - `PpuSetWidescreenWindowExpansion`, `PpuSetWidescreenLayerMask`,
    `PpuSetWidescreenBg3Widen`, `PpuSetWidescreenLayerMarginGap/ViewportInset`;
  - `PpuSetWidescreenLineEnhancer` (callback host-only que substitui pixels
    obsoletos das margens antes da composição).
- **`runner/src/snes/ws_shadow.c`** — histórico de tilemap por coordenada de
  mundo: `WsShadowSetWorld/SetScroll`, `SetPeriodicFold`,
  `SetRetainHistory`, `SetWestKeep/SetEastKeep`, `PrefillTile/ForceTile`,
  `ExtendEdges`, `WsShadowFrame` (chamado pelo jogo após rasterizar),
  estatísticas de acerto/erro das margens.
- **`runner/src/widescreen.c`** — `RtlWidescreenPresent` e a política
  compartilhada de `g_ws_active/g_ws_extra`.
- **`desktop/display_aspect.h`** — `SnesDisplayAspect_ComputeAdaptiveFrame`
  (largura/clamp de aspecto), `FitViewport`, `ComputeWindowWidth`.
- **`desktop/host_main.h`** — hooks `prepare_frame`, `begin_sim_frame`,
  `end_sim_frame`, `draw_frame`, `compute_viewport`, `window_base_width/height`;
  flags `widescreen_supported` e `native_widescreen` (com `native_widescreen=1`
  o host chama `PpuSetExtraSpace` sozinho a cada frame).
- **Sistema de mods** — pacote `manifest.toml` + plugin de ativação registrado
  com `snes_mod_register_activation_plugin` + `snes_mod_register_reset_callback`
  (`snesrecomp/docs/MOD_PACKAGES.md`). É assim que o MMX ativa/desativa o
  widescreen, lê a opção de aspecto e persiste o estado.
- **`docs/WIDESCREEN_PATTERNS.md`** — a doutrina P1–P16, checklist obrigatório.

### 2.2 As duas trilhas do MMX

| | X1 (custom renderer, v1.5+) | X2/X3 (nativo, `mmx23_host_main.inc`) |
|---|---|---|
| Campo | compositor próprio até 1024px | `PpuSetExtraSpace` do framework |
| Fundos | lê mapas de nível retidos + definições de metatile do ROM | políticas do PPU + `WsShadow` |
| Sprites | captura pré-clipping do emissor OAM (`MmxRendererRecordPiece`), capacidade extra opcional | widening de OAM no PPU + hooks de cull |
| HUD | relocação de sprites por assinatura | clamps/bands de BG3 + OAM shift |
| Spawn | dual pass com cursor largo persistente | idem (mesmos hooks `WS-*`) |
| Custo | ~133 KB de renderer + 44 KB de assets + política | dezenas de linhas de política |

O X1 só foi para o compositor porque casos específicos (céu de Storm Eagle,
submarino de Launch Octopus, paletas de fundo distantes, *streakers*) exigiam
amostragem do mapa retido, preview de inimigos e reparo de CHR. Demon's Crest
tem um pipeline **mais simples e melhor documentado em WRAM** (§3), então a
trilha nativa é a aposta certa.

### 2.3 Peças do MMX que valem copiar

- `src/mods/mmx_widescreen_plugin.c` — ativação/reset do mod e leitura da
  opção de aspecto via `snes_mod_runtime_launcher_provider_c()`.
- `MmxDisplay_ComputeFrameWidth` / `MmxRendererViewport` — cálculo de largura
  (even, clampado) a partir de Adaptive/16:9/21:9/32:9 + `display_aspect`.
- `tools/apply_overrides.py` + `apply_renderer_capture.py` — injeção
  idempotente de hooks no C gerado, com marcadores `/*WS-*/\n` e falha
  explícita se um âncora sumir no regen (disciplina de regen-drift).
- `mmx_wide_policy.c` — catálogo de decisões (cull, leash, ativação,
  cursor de spawn por passada) e a separação "passada larga = inimigo comum /
  passada nativa = progressão" (P10) com cursor persistente.
- `mmx_display.c` — `MmxDisplay_ExpandStageScroll`: recupera a fase de 8 bits
  do tilemap circulante a partir da câmera completa (mesmo problema existirá
  no DC).

### 2.4 Lições (P1–P16) que o plano incorpora

P1 fase do scroll vem do PPU; P2 margens pré-preenchidas antes de aparecerem;
P2b reflexão nas bordas do mundo; P3 camadas periódicas dobráveis; P5/P6 gate
de "gameplay vivo" com evidência observável; P7/P8 cull **e** emissor OAM em
conjunto (o compare de X é unsigned); P9 folga de margem+32; P10 spawn largo
não alarga progressão (dual pass); P11 passada nativa como chamada sintética
balanceada; P12 objetos grandes precisam de distância de ativação alargada;
P13 viés de staging de CHR/tilemap ≤ margem e só na direção do movimento;
P14 kill-switches independentes; P15 previews cedem ao spawn real;
P16 4:3 bit-idêntico e simulação intocada.

---

## 3. O motor de Demon's Crest (levantamento no ROM)

Tudo abaixo foi verificado por disassembly do ROM unheadered (CRC32
`e8236ad2`) com `tools/disasm_range.py` e varredura de padrões. Endereços em
`banco:offset` LoROM FastROM (`$80+`).

### 3.1 Vídeo

Init em `$80:884C` (`$80:8850` = `STA $2105`):

| Registro | Valor | Significado |
|---|---|---|
| `$2105` BGMODE | `$09` | **Mode 1** + prioridade BG3 |
| `$2107` BG1SC | `$49` | mapa BG1 em VRAM word `$4800`, 64×32 |
| `$2108` BG2SC | `$41` | mapa BG2 em `$4000`, 64×32 |
| `$2109` BG3SC | `$5A` | mapa BG3 em `$5800`, 32×64 |
| `$210B` BG12NBA | `$00` | CHR BG1/BG2 em `$0000` |
| `$210C` BG3NBA | `$05` | CHR BG3 em `$5000` |
| `$212C` TM | `$17` | BG1+BG2+BG3+OBJ |

O loader de sala troca `$2107`/`$2108` (`$80:CC8A` e `$80:CCF8`) — BG1 e BG2
alternam papéis por sala (provavelmente salas espelhadas). O HUD BG3 é
recarregado de `$7F:B000` para `$5800` (`$80:CC9A`, 2 KB) e reescrito linha a
linha em `$80:C9xx`.

### 3.2 Câmera e scroll

O NMI `$80:8329` copia os *mirrors* de DP para os registros, byte baixo e
alto, todos os frames:

| DP | Registro | Papel |
|---|---|---|
| `$A2/$A3` | `$210D` | BG1 HOFS |
| `$A6/$A7` | `$210E` | BG1 VOFS |
| `$A4/$A5` | `$210F` | BG2 HOFS |
| `$A8/$A9` | `$2110` | BG2 VOFS |
| `$AA/$AB` | `$2111` | BG3 HOFS |
| `$AC/$AD` | `$2112` | BG3 VOFS |
| `$AE/$AF/$B0/$B1` | `$212C..2F` | TM/TS/TMW/TSW |
| `$B7` | `$420C` | HDMAEN |
| `$A0` | `$2100` | INIDISP |

A câmera de jogo é **`$C0` (X) e `$C4` (Y)**, 16 bits. No loop de gameplay
`$80:B017`:
- `$C0 → $C8` (cópia exata) e `$C0 & $03FF → $A2` (scroll BG1);
- `$C4 → $CA` e `$C4 & $03FF → $A6`;
- `$F0 = $C0 + $80` e `$F2 = $C4 + { $C8 | $30 | $70 | 0 }` conforme sala —
  centros do **Mode 7** (usado por efeitos/chefes, não no BG principal).
- BG2 (`$A4/$A8`) recebe o parallax de `$C2/$C6` (metade, via `$80:CBAB`).
- Máscaras `$B8/$BA/$BC/$BE` (`$01FF`/`$00FF`) entram nos caminhos de init
  (`$80:A8D4`).

### 3.3 Sala: layout, colisão, metatiles e streaming

- **Parser do layout** `$80:C69F`:
  - 1º byte do registro = `$79` (**largura** em células 16×16), 2º = `$7A`
    (**altura**); loops copiam `$79 × $7A` bytes para `$7E:8000` (mapa de
    colisão) e há seções opcionais espelhadas em `$7E:8080` (`$7B/$7C`).
  - Depois vêm listas de IDs de objeto/evento tratadas por `$84:9BC9` e
    `$84:9C5B`.
- **Colisão** `$80:94D3`: índice = `x + y*$79` em `$7E:8000`, atributos em
  `$7E:2000`, tabela de física no ROM `$98:8000` → `$16`.
- **Metatiles**: definições de 16 bytes (4 tiles 8×8) expandidas para
  `$7F:C000`/`$7F:C800` (páginas 32×32 de tilemap, `$80:CC0A`), e as páginas
  vão para VRAM por DMA (`$80:CD10`, 2×2 KB para `$4000`/`$4800`).
- **Decompressor** de asset da sala `$84:9E03` grava 16 KB via porta WRAM
  (`$2181/$2182/$2183`) em `$7F:4000` (gráficos da sala).
- **Fila de DMA de VRAM** no NMI `$80:8543`: `$87` (bitmask) dispara uploads
  fixos de `$81:8068` para `$4800`, `$4000` e `$5800`; `$81`/`$82` são filas de
  descritores de 8 bytes em `$0500`/`$0600` (VMAIN, VMADD, tamanho, origem,
  banco). Ou seja, **tilemaps são circulantes** — a margem pode conter páginas
  obsoletas se não houver preenchimento host-side.
- **Câmera e página**: o streaming compara a posição (`$0E82/$0E86`) com a
  página atual e reescreve meia tela (`$80:C522` ~0x200 bytes), exatamente o
  caso que `WsShadow` + prefill resolvem (P2/P4).

### 3.4 Objetos e spawn

- Slots: base `$1080`, **stride `$50`**, até `$1D50` → 41 slots; o jogador
  (Firebrand) em `$1000`, mesmos campos.
- Campos: `+$00` flags (bit 4 = visível/na tela, bit 7 = espelhado),
  `+$02` handler/estado (word, tabela de saltos), `+$0B` flags de sprite,
  `+$20/$22` velocidade X/Y, `+$30/$33` **posição X/Y (16 bits)**,
  `+$2C` contador de suspensão.
- **Loop de update** `$82:860E` (varre todos os slots) com **cull**:
  - X: `$82:86E2` `(objX − $C0 + $60) < $1C0` (janela −96…+352 em relação à
    câmera);
  - Y: `$82:86F3` `(objY − $C4 + $60) < $1A0`;
  - ao passar, seta bit 4 de `$00` (`$82:8704`) e escreve `$0A00` (dx do
    objeto, usado por efeitos).
- **Templates**: IDs de objeto → registros de 6 bytes no ROM `$99:8000`
  (`$84:9BC9`), postos em staging (`$0D00`); a fila de spawn pendente fica em
  `$7F:A000` e é drenada por `$84:9C04`/`$84:9C5B` (registro de 11 bytes com
  X/Y, tabela `$C125`).
- **IDs de sprite** por sala: `$0D30` (comentário do disassembly parcial:
  "list of sprite IDs for this stage").
- Progressão: `$1E51`/`$1E54` (bitmasks de conclusão por área); área `$8D`,
  sala/índice `$F9`; contadores de tela `$F8`, `$0E53`.

### 3.5 Sprites/OAM

- Buffer de OAM em `$0700` (0x220 bytes), DMA no NMI.
- Metasprite do objeto atual em `$7F:1000`; *builder* em `$80:F720+`:
  - escreve X em `$0700`, Y em `$0701`, tile em `$0702`, atributo em `$0703`;
  - **cull direito** em `$80:F75C` (`and #$00FF; cmp #$00F3; bcc`), com
    tratamento do bit de 9º (X negativo/salto);
  - `$0900` (flags por slot), `$0960` (tile base), `$0980` (paleta) mantidos em
    paralelo; tabelas `$B7C9`/`$B7D9` ligam/desligam bits.
- O PPU do framework já compõe sprites fora dos 256px quando o campo é
  alargado (`extraLeftCur/extraRightCur` em `ppu.c`, linhas ~1810/2685), mas o
  **emissor do jogo** corta antes — é o P8.

### 3.6 HUD

- BG3 superior-esquerdo construído em `$80:C9xx` a partir de:
  - `$1065` (vida atual), `$1E30` (vida máxima, com ajuste `−20`),
  - `$12E8` (magia/nível), e IDs de tile `$2062/$2063/$2072/$2073/$2064/$2065`;
  - mapa escrito em `$7F:B000` e DMA'do para `$5800`.
- `$0E57/$0E58/$0E5B` alimentam as janelas `$2126..$2129/$2125` — a área do
  status bar pode usar *window* de hardware, a confirmar em runtime.
- BG3 também é usado em efeitos (comentários de MMX/X2 mencionam chuva no
  subscreen); no DC ainda não catalogados — a política por linha
  (`ClampBand`/`AnchorBand`) permite tratar só as linhas do status.

### 3.7 Tabela consolidada

| Endereço | Papel |
|---|---|
| `$80:8329` | NMI: scrolls, OAM DMA, CGRAM, filas de VRAM, HDMA |
| `$80:8543` | uploads fixos de tilemap (`$87`) + filas `$81`/`$82` |
| `$80:884C` | init Mode 1 (`$2105..$210C`, TM) |
| `$80:B017` | gameplay: câmera→scroll, centros Mode 7 |
| `$80:94D3` | consulta de colisão (`$7E:8000`, `$7E:2000`, `$98:8000`) |
| `$80:C69F` | parser de layout da sala (`$79/$7A`, mapas) |
| `$80:CC0A` | expansão de metatiles → páginas `$7F:C000/$C800` |
| `$80:CC9A` / `$80:CD10` | DMA das páginas para `$5800` / `$4000`,`$4800` |
| `$80:C9xx` | construtor do HUD (BG3) |
| `$80:F720` | emissor OAM (buffer `$0700`) |
| `$80:F75C` | cull direito do OAM (~`$F3`) |
| `$82:860E` | loop de update dos 41 objetos |
| `$82:86E2` / `$82:86F3` | cull X / Y dos objetos |
| `$84:9BC9` | template de objeto (banco `$99`, 6 bytes) |
| `$84:9C04` | fila de spawn pendente (`$7F:A000`) |
| `$84:9C5B` | registro de spawn/evento (11 bytes, `$C125`) |
| `$84:9E03` | decompressor de asset da sala → `$7F:4000` |
| `$A2..$AD` | mirrors de scroll por camada |
| `$C0/$C4` | câmera X/Y (16 bits) |
| `$C2/$C6` | scroll BG2 (parallax; `$80:CBAB` = metade) |
| `$C8/$CA` | cópia exata da câmera por frame |
| `$79/$7A` | largura/altura da sala (células 16×16) |
| `$8D` / `$F9` | área / sala |
| `$1000`, `$1080+$50n` | jogador e objetos |
| `$1E51/$1E54` | progresso |

> Onde a confirmação depender de runtime (modo de jogo, janelas do HUD, uso de
> BG3 em efeitos), a Fase 2 define o procedimento de watchpoints/`poke` sobre o
> harness headless antes de fixar qualquer gate.

---

## 4. Decisão de arquitetura

**Adotar a trilha nativa do framework** (como X2/X3): `native_widescreen = 1`,
`prepare_frame` decide a largura, `PpuSetExtraSpace` é do host, e um módulo
`dc_widescreen.c` publica por frame:

1. gate de cena (gameplay vs. menus/cutscenes);
2. políticas de BG3 (clamp do HUD, bands por linha);
3. política de BG1/BG2 (margem natural + `WsShadow` + prefill do cache de
   metatiles da sala, e/ou `WorldMirrorBand` para salas limitadas);
4. `PpuSetWidescreenLineEnhancer` com um resolvedor de tiles que lê o cache
   host-side do mapa da sala (somente leitura, sem tocar em VRAM/CPU).

**Critérios objetivos para acionar a contingência (Fase 8, compositor custom):**

- margens exigem conteúdo que não pode ser reconstruído do cache de sala
  (ex.: sprites/CHR que só existem em VRAM depois de triggers que não podemos
  disparar cedo sem quebrar progressão);
- o page builder do jogo reescreve colunas fora da tela de forma que o
  `line enhancer` não consegue estabilizar (ver a experiência do X1 com
  streakers e o céu de Storm Eagle);
- custo/benefício do trade-off "mexer no guest (staging adiantado)" for
  rejeitado na validação P13.

Só então portar a arquitetura do `mmx_renderer.c` (captura de raster,
decodificador Mode 1, assets, capacidade de sprite), **nunca** o arquivo em si.

---

## 5. Plano de implementação

### Fase 0 — Pré-requisitos (antes de tudo)

1. Port jogável: título → file select → primeira fase com input roteirizado
   (o harness já suporta `press`, `until`, `poke`; criar
   `scripts/routes/gameplay.script`). Widescreen não se valida sem gameplay.
2. Congelar baseline 4:3: capturas `dump <tag>` em pontos fixos + SHA-256 de
   `SNESRECOMP_STATE_TRACE` da rota (o critério P16 usa diff de frames com o
   mod desligado antes/depois).
3. Nomear símbolos mínimos em `recomp/symbols.toml` para os endereços do §3.7
   (NMI já nomeado; adicionar `RoomLoad`, `ObjUpdate`, `OamBuild`, etc.) e
   regenerar. Isso deixa os hooks de Fase 4/5 com âncoras estáveis.

**Saída:** rota de gameplay determinística e baseline 4:3 versionada em
`docs/verification/`.

### Fase 1 — Plumbing inerte (pode começar já)

1. `docs/WIDESCREEN_PLAN.md` (este documento).
2. Pacote `mods/preloaded/packages/demons-crest.enhancement.widescreen/1.0.0/manifest.toml`
   (copiar do MMX; `game_id = "demonscrest-usa"`, SHA-256 do
   `rom_identity.txt`; feature `widescreen` default off; opção `aspect`
   Adaptive/16:9/21:9/32:9; plugin `demons-crest.widescreen`).
3. `src/mods/dc_widescreen_plugin.c` — ativação/reset, leitura da opção de
   aspecto (padrão `mmx_widescreen_plugin.c`).
4. `src/dc_display.c/.h` — `DcDisplay_ComputeFrameWidth(aspect, dw, dh, display_aspect)`
   com `SnesDisplayAspect_ComputeAdaptiveFrame`, clamp par e teto
   `kPpuBufWidth` (o teto do host para `native_widescreen`, 800px);
   `DcDisplay_GetWindowBaseWidth/Height`.
5. `src/dc_widescreen.c/.h` — esqueleto com `g_dc_widescreen` e
   `DcWidescreenConfigureFrame()` vazio.
6. `src/main.c` — adicionar `.widescreen_supported = 1`, `.native_widescreen = 1`,
   `.prepare_frame = DcPrepareFrame` (retorna 256 quando o mod está off — inerte).
7. `CMakeLists.txt` — novos fontes no alvo (sem `apply_*` ainda).

**Validação:** build limpo; mod aparece no launcher; com o mod off, 4:3
bit-idêntico (baseline da Fase 0); com o mod on num port ainda scaffold, a
janela alarga e o PPU renderiza margens vazias — sem crash.

### Fase 2 — Gate de cena e políticas de tela cheia

1. Mapear, com watchpoints/`poke` e capturas, o discriminador "gameplay vivo":
   candidatos `$86` (modo do NMI), `$8D`≠0 (área ativa), `$F9`, `$F8`,
   `$0E53`; exigir uma consequência observável (P6), não só o byte de modo.
2. Fora do gameplay (logos, título, password, file select, cutscenes de tela
   cheia): clamp de todas as camadas BG (pillarbox; as margens ficam só com o
   backdrop). Não usar `PpuSetExtraSpaceCentered` aqui: ele não escreve as
   margens (o chamador teria de apagá-las) e um buffer reaproveitado mostra
   pixels da cena anterior.
3. Publicar por frame em `begin_sim_frame`:
   - `PpuSetWidescreenLayerClamp`/`LayerMask` conforme a cena;
   - `PpuSetExtraSideSpace` com margens simétricas clampadas às bordas do mundo
     quando a sala for limitada (P2b).
4. Criar `tools/dc_apply_widescreen_hooks.py` (idempotente, marcadores
   `/*DCWS-*/`, falha se âncora sumir) e ligar no CMake como `OBJECT_DEPENDS`,
   nos moldes de `MMX -> apply_overrides.py`.

**Validação:** navegar por todos os modos (intro, título, menu, gameplay,
pausa, morte) e conferir por captura que nenhum deles ganha margem indevida.

### Fase 3 — Fundos BG1/BG2

1. Cache host-side do mapa da sala: hook somente-leitura no parser `$80:C69F`
   capturando `$79/$7A`, o buffer de mapa, o ponteiro das definições de
   metatile e o banco; manter uma cópia por sala (`$8D`/`$F9`) com validação
   de época (nunca escrever no guest).
2. Registrar `WsShadowSetWorld` para BG1/BG2 com a câmera `$C0/$C4` (câmera é
   a base de mundo; scroll do PPU dá a fase — P1), `SetRetainHistory` e
   `SetWestKeep/SetEastKeep` dimensionados pela margem (P4).
3. Chamar `WsShadowFrame(g_ppu)` após o raster de cada frame (hook
   `end_sim_frame` ou no `GameDrawPpuFrame`).
4. Prefill host-side (`WsShadowPrefillTile`) a partir do cache de sala para
   margens ainda não visitadas (P2). Se o cache não cobrir (ex.: página que o
   jogo ainda não expandiu), usar `PpuSetWidescreenLineEnhancer` para resolver
   tiles direto do mapa de metatiles + definições (mesma técnica do
   `mmx_wide_preview`/renderer, mas emitindo linhas de PPU).
5. Para salas com fundo periódico (céu/água), `WsShadowSetPeriodicFold` (P3).
6. `SNESRECOMP_WS_BG` como kill-switch dessa fase.

**Validação:** andar para os dois lados; a coluna mais externa deve estar
correta no primeiro frame em que aparece; comparar `WsShadowGetMarginStats`
(hits/misses/folds) entre andar ↔ parar; conferir ausência de "corte de
pilar" no seam (P1).

### Fase 4 — Sprites e OAM

1. Hook no cull do update de objetos (`$82:86E2`/`$82:86F3`): substituir as
   comparações por uma veredito host-side
   `DcWsObjectCullVerdictX/Y(dx, margin)` que alarga **os dois lados** sem
   mudar a base da janela (P7):
   `keep = (dx + m + 0x60) < (0x1C0 + 2m)` (X) e idem `0x60/0x1A0` (Y).
2. Hook no emissor OAM (`$80:F75C` e o teste do bit de 9º/"negativo"):
   alargar o limite direito e **substituir** o compare do lado esquerdo por
   `DcWsOamXReject(x9, limit)` (P8) — o PPU já compõe fora dos 256px.
3. Setar o bit de visibilidade (`$82:8704`, bit 4 de `$00`) para objetos que
   entrem nas margens, garantindo que a física/OAM deles atualize.
4. Se objetos grandes "poparem" pelas pontas, alargar a distância de ativação
   (P12) e a folga do spawn (P9: margem+32).
5. Kill-switch: `SNESRECOMP_WS_OAM` (fallback = só cull alargado, sem emissor).

**Validação:** inimigo estradando as duas bordas da margem (não só a direita)
permanece desenhado; capturas antes/depois com 4:3 bit-idêntico (P16).

### Fase 5 — Spawn e progressão

1. Localizar (watchpoints em `$1080`/`$7F:A000` + `$84:9C04`/`$84:9C5B`) o
   ponto exato em que o spawn de sala compara a posição com a câmera.
2. Implementar **dual pass** desde o início (P10/P11):
   - passada larga: só inimigos comuns; cursor largo persistente por sala
     (`DcWideSpawnCursor`, padrão `MmxWidePolicy_BeginWideSpawnPass`);
   - passada nativa: tudo (chefes, gatilhos de câmera, eventos, coletáveis
     especiais), com chamada sintética balanceada (salvar/restaurar `CpuState`
     e bytes de âncora).
3. Invalidar/ressincronizar o cursor largo em morte/reset/load de estado
   (equivalente a `MmxWidePolicy_WideSpawnCursorPersists`).
4. Identificar famílias "scriptadas" por área (chefes, cutscenes de arena) e
   forçá-las à passada nativa (`ForceNativeSpawnTiming`).
5. Kill-switches `SNESRECOMP_WS_SPAWN` (spawn largo) e `SNESRECOMP_WS_STAGE`
   (staging), independentes (P14).

**Validação:** rota de gameplay com a mesma sequência de encontros e eventos
da versão nativa; inimigos aparecem 32px além da borda visível, nunca dentro
dela (P9); sem locks de câmera adiantados.

### Fase 6 — HUD

1. BG3: manter o status bar ancorado à **esquerda** com
   `PpuSetWidescreenLayerAnchorBand(2, y0, y1, left_end≈256, right_start=256)`
   nas linhas do HUD (o bar é superior-esquerdo) e `ClampBand` nas demais;
   alternativamente `PpuSetWidescreenLayerElasticBand` se o chrome do bar
   esticar mal.
2. Se as linhas do HUD forem confirmadas por janela de hardware
   (`$0E57/$0E58/$0E5B` → `$2126..`), tratar por linha/estado (testador P2c).
3. Sprite HUD fora dos 256px (se houver): `PpuSetWsHudOamShiftRange` (1ª/2ª
   faixa), publicados a cada frame.
4. Medir os runs rígidos/elásticos do bar **com a camada isolada**
   (`SNESRECOMP_LAYER_MASK`) antes de fixar segmentos (P2c).

**Validação:** todos os estados da barra (vida cheia/vazia, magia, dano,
pickup) sem glyphs deformados nem buracos; HUD move para a borda esquerda com
o campo alargado.

### Fase 7 — Validação e release

1. Repetir a checklist P1–P16 registrando para cada item: método, captura e
   resultado (o framework exige isso no doc do título).
2. Suíte própria:
   - determinismo: 2 execuções da rota com `SNESRECOMP_STATE_TRACE`
     byte-idênticas, com mod on;
   - 4:3 bit-idêntico (P16) com mod off;
   - `SNESRECOMP_WS_EXTRA=43` (probe determinístico) em telas de verificação;
   - `SNESRECOMP_FRAME_BMP_DIR` para séries de frames;
   - save-state load no meio da fase (cursor largo, `WsShadow`, margens).
3. `docs/WIDESCREEN.md` do projeto: o que foi verificado, kill-switches,
   opções e limitações.
4. Preparar `tools/play.ps1` equivalente (regen + build + launch) se desejado.

### Fase 8 — Contingência: compositor custom

Acionar só pelos critérios do §4. Passos (arquitetura do X1, código novo):

1. `dc_renderer.c`: captura por linha (registradores/paleta/VRAM/OAM do
   raster), buffer de saída até 1024px, composição Mode 1 (BG1/BG2/BG3+OBJ).
2. Amostragem das margens a partir do cache de sala (metatiles + definições)
   em vez de VRAM circulante.
3. Captura pré-clipping dos sprites no emissor OAM (equivalente ao
   `apply_renderer_capture.py`) para desenhar peças descartadas pelo jogo.
4. Relocação do HUD e capacidade de sprites opcional (ArrayList 2048).
5. `draw_frame` próprio e testes 4:3/16:9/21:9/32:9 conforme o doc do X1.

---

## 6. Estrutura de arquivos e ligação no CMake

```cmake
# CMakeLists.txt (aditivo, no mesmo alvo de snesrecomp_target_generated_code)
add_executable(DemonsCrestSNESRecomp
    ...
    src/dc_display.c
    src/dc_widescreen.c
    src/mods/dc_widescreen_plugin.c
)
# o projeto gera em ${CMAKE_SOURCE_DIR}/src/gen (ver snesrecomp_target_generated_code)
file(GLOB dc_generated ${CMAKE_SOURCE_DIR}/src/gen/*.c)
set_property(SOURCE ${dc_generated} APPEND PROPERTY OBJECT_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/tools/dc_apply_widescreen_hooks.py)
add_custom_target(DemonsCrest_widescreen_hooks
    COMMAND ${Python3_EXECUTABLE} tools/dc_apply_widescreen_hooks.py
            --gen-dir ${CMAKE_SOURCE_DIR}/src/gen
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR} VERBATIM)
add_dependencies(DemonsCrestSNESRecomp DemonsCrest_widescreen_hooks)
# o projeto hoje não chama find_package(Python3 ...); adicionar como no MMX.
```

`src/main.c` (delta):

```c
static void DcPrepareFrame(int dw, int dh, int *w, int *h) {
  *w = g_dc_widescreen ? DcDisplay_ComputeFrameWidth(g_dc_aspect, dw, dh,
                              SnesDisplayAspect_Clamp(g_config.display_aspect))
                       : 256;
  *h = 224;
}
static void DcBeginFrame(unsigned n) { DcWidescreenConfigureFrame(); }
...
.widescreen_supported = 1, .native_widescreen = 1,
.prepare_frame = DcPrepareFrame, .begin_sim_frame = DcBeginFrame,
```

`manifest.toml` (deltas vs. MMX): `game_id = "demonscrest-usa"`,
SHA-256 do `rom_identity.txt`, plugin `demons-crest.widescreen`.

---

## 7. Hooks no código gerado (`tools/dc_apply_widescreen_hooks.py`)

Padrão do MMX: regex sobre `src/gen/*.c`, marcador idempotente, falha dura se
a âncora não casar (regen-drift). Âncoras do DC:

| Marcador | Âncora | Injeção |
|---|---|---|
| `/*DCWS-CULL-X*/` | `$82:86E2` `sbc $00C0` → comparação `cmp #$01C0` | `cpu->_flag_C = DcWsObjectCullVerdictX((uint16)_vN);` |
| `/*DCWS-CULL-Y*/` | `$82:86F3` análoga (`$01A0`) | idem Y |
| `/*DCWS-OAM*/` | `$80:F75C` `cmp #$00F3` | `_vN = DcWsOamRightLimit(_vN);` |
| `/*DCWS-OAM-L*/` | teste do 9º bit/normalização de X no emissor | `cpu->_flag_C = DcWsOamXReject(x9, limit);` |
| `/*DCWS-SPAWN*/` | ponto de spawn de sala (Fase 5, watchpoints) | cursor largo + `DcWsSpawnRecordAllowed` |
| `/*DCWS-STAGE*/` | gatilhos de staging de CHR/tilemap por coluna | viés ≤ margem na direção do movimento (P13) |

Regras: nunca escrever estado guest sem necessidade; toda função host
consultada é determinística e derivada de RAM (compatível com save-state,
rewind e netplay); cada hook tem um kill-switch.

---

## 8. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Port ainda scaffold: sem gameplay não há como validar nada além de plumbing | Fases 0–1 primeiro; widescreen só avança com rota jogável |
| Mapa circulante em VRAM (64×32, páginas de 32×32) expõe lixo nas margens | `WsShadow` + prefill do cache de sala + line enhancer (Fase 3) |
| BG1/BG2 trocam de base por sala; papéis de parallax variam | política por frame lendo `$2107`/`$2108` reais do PPU, não por suposição |
| BG3 também usado em efeitos (X2/X3 usam chuva no subscreen) | política por linhas/estado; catálogo de situações via captura (Fase 6) |
| Emissor OAM com compare unsigned de X (P8) deixa margens esquerdas vazias | hook dedicado `DCWS-OAM-L`; teste de straddle nas duas bordas |
| Spawn largo altera progressão/RNG | dual pass (P10) + cursor persistente + famílias scriptadas na passada nativa |
| Staging de CHR adiantado corrompe gráficos compartilhados (P13) | viés ≤ margem na direção do movimento, kill-switch `SNESRECOMP_WS_STAGE` |
| Regen futuro quebra as âncoras dos hooks | falha explícita do injetor + CTests de cobertura dos marcadores |
| Save-state/rewind com estado host novo | estado host derivado de RAM; nada persistido além de contadores invalidáveis por sala |

---

## 9. Critérios de aceitação

1. Mod off = 4:3 bit-idêntico ao baseline (P16).
2. 16:9/21:9/32:9/Adaptive estáveis em gameplay, com HUD legível ancorado.
3. Inimigos desenhados e atualizando em ambas as margens, sem pop-in visível
   (folga P9).
4. Nenhum lock de câmera, encontro de chefe ou evento disparado cedo; ordem de
   spawn fora da margem igual à nativa.
5. Sem lixo de tilemap nas margens em salas visitadas nos dois sentidos e em
   load de estado no meio da fase.
6. Determinismo preservado (duas execuções idênticas com o mod on).
7. Checklist P1–P16 registrada em `docs/WIDESCREEN.md` com método e evidência.

---

## 10. Referências

- `M:\Opencode\MegaManXSNESRecomp`:
  - `src/mmx_renderer.c/.h`, `src/mmx_render_assets.c`, `src/mmx_wide_policy.c/.h`,
    `src/mmx_wide_preview.c/.h`, `src/mmx_display.c/.h`, `src/main.c`;
  - `src/mods/mmx_widescreen_plugin.c`,
    `mods/preloaded/packages/megaman-x.enhancement.widescreen/1.0.0/manifest.toml`;
  - `tools/apply_overrides.py`, `tools/apply_renderer_capture.py`;
  - `docs/custom-renderer-spike.md`, `docs/magic-carpet.md` (histórico de
    playtest e compatibilidade).
- `snesrecomp/` (pin `eb75c88`):
  - `docs/WIDESCREEN_PATTERNS.md` (P1–P16),
  - `docs/MOD_PACKAGES.md`, `docs/FRAME_MODEL_HOSTS.md`, `docs/GAME_PROJECT_SETUP.md`,
  - `runner/src/snes/ppu.h`, `runner/src/snes/ws_shadow.h`, `runner/src/widescreen.h`,
  - `runner/src/desktop/host_main.h`, `runner/src/desktop/mmx23_host_main.inc`,
    `runner/src/desktop/display_aspect.h`.
- Demon's Crest: disassembly parcial da comunidade
  (`FredYeye/various-game-disassembly`, `SNES/demons_crest.asm`) — útil para
  nomes, incompleto; os endereços deste plano foram verificados no ROM local.
