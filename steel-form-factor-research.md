# Steel Form-Factor Domain Research (Semi-Finished / Mill Products)

**Purpose:** This document is domain research to inform a future standalone steel-audit
rubric (structured like `postgres-database-audit-rubric.md` but for steel-specific data
shapes, sensors, tolerances, and traceability). It is **not** the rubric itself — no
scoring model, question bank, or audit checklist is defined here. Scope is bulk
**semi-finished and mill-stage steel products** only (Semi-Finished Input, Flat Mill
Products, Long Mill Products, Tubular). Finished bulk products (fasteners, nails, wire
mesh, chain, wire rope/cable, springs, pipe fittings) are explicitly out of scope.
Aluminum and copper are deferred/out of scope per prior scoping decision. Standards
citations were checked against current search results where possible; anything not
independently verifiable is flagged rather than presented as fact.

---

## Core Data Profile

These data elements recur across **all four** delta clusters below. Cluster sections
only list what's *additive* on top of this core — treat any field described here as
already present in every cluster's schema.

### 1. Heat / lot identity and traceability chain
- **Heat number**: the primary identity key, assigned at the melting stage (BOF or EAF
  furnace heat / ladle). One heat produces one chemistry population; permissible
  chemistry variation is defined relative to the heat, not the piece.
- **Cast / strand number**: continuous casting divides one heat across multiple casting
  sequences/strands, so a single heat can span multiple cast pieces. The heat → cast →
  piece hierarchy is universal to all four clusters and is the backbone of any
  traceability schema — a rubric should treat "heat number" and "piece/coil/bundle ID"
  as two distinct, hierarchically related keys, not one field.
- **Downstream lot/sub-lot IDs**: each subsequent process step (hot rolling, cold
  rolling, pickling, slitting, drawing, coating) commonly assigns its own lot or coil
  ID while a physical or documentary link back to the heat number is preserved (stamped,
  tagged, or carried in ERP/MES lot-genealogy tables). This is the most common place
  traceability breaks in practice — a schema-drift / lost-linkage risk applies at every
  hand-off between process steps, not just at the mill boundary.
- Physical marking convention: heat number is typically **hard-stamped, paint-marked, or
  tagged** directly on the product (per product-spec marking clauses, e.g. within
  ASTM A6/A6M for structural products); data schemas should distinguish the
  *physical-mark* record from the *system-of-record* lot record, since these can
  diverge (mis-stamping, faded tags, re-tagging after cutting).

### 2. Chemistry / composition against a grade specification
- Two distinct chemistry records recur industry-wide: **heat (ladle) analysis** (taken
  from the melt) and **product (check) analysis** (taken from the finished piece,
  subject to a separate, wider permissible-variation tolerance band than heat analysis
  in most ASTM product specs, e.g. ASTM A6/A6M and A29/A29M both define check-analysis
  tolerance tables distinct from heat-analysis limits). A rubric should model these as
  two related records, not one.
- Composition is always evaluated **against a grade specification** — an ASTM grade
  (e.g., A36, A992), an SAE/AISI designation (e.g., 1018, 4140 — first two digits =
  alloying series, last two/three = carbon content in hundredths of a percent, per the
  SAE/AISI numbering system), or a customer/proprietary grade. The core schema needs a
  grade-spec reference field plus the element-by-element chemistry values (C, Mn, P, S,
  Si, and alloying elements as applicable: Cu, Ni, Cr, Mo, V, etc.), not just a pass/fail
  flag.

### 3. Mill Test Report / certification reference
- **Correction to an initial assumption going into this research**: there is **no single
  ASTM standard that defines "the" Mill Test Report format.** ASTM A1032 (verified via
  search) is unrelated — it's a hydrogen-embrittlement test method for prestressed-
  concrete-pipe wire, not a certification standard. ASTM A941 is a **terminology**
  standard (definitions), not a certification/report-format standard. In practice, MTR
  content requirements live inside each product specification's own certification
  clause (e.g., ASTM A6/A6M has a certification/report section) plus purchase-order
  requirements, and the internationally recognized *format/type* taxonomy is **EN
  10204** (Types 2.1, 2.2, 3.1, 3.2 — with 3.1 being the common "independently validated
  test report tied to the specific heat" tier used in pressure/oil-and-gas and
  increasingly general industrial procurement). A rubric's core schema should treat
  "certificate type" (EN 10204 tier, if used) and "governing product spec" as separate
  fields, and should not assume a single universal MTR schema — MTR field sets vary by
  product spec and customer PO.

### 4. Dimensional tolerance concept
- Every cluster has *a* governing dimensional-tolerance concept, but *which* dimensions
  apply is cluster-specific (thickness/width/camber for flat products; diameter/
  straightness for bar and rod; OD/wall-thickness for pipe; cross-section/length for
  billet). The core schema should carry a generic
  {measured-dimension, nominal, plus-tolerance, minus-tolerance, measurement-method}
  tuple pattern that each cluster populates differently, rather than hardcoding
  dimension names at the core level.

### 5. Unit-of-sale convention
- Bulk semi-finished/mill steel is conventionally sold **by weight (net tons / metric
  tonnes)**, with secondary per-piece, per-coil, per-length, or per-sheet counts carried
  alongside for reconciliation. Any schema needs both a weight field and a count/
  length field, with an explicit conversion or reconciliation relationship — this is a
  recurring source of unit-of-sale ambiguity in vendor/mill data (theoretical weight
  from nominal dimensions vs. actual scaled weight).

### 6. Timestamp / process-run / sensor-ID metadata conventions
- Every cluster's process data is generated by inline sensors on a moving line (caster,
  rolling mill, drawing line, pipe mill) and is naturally **time-series** in shape:
  timestamp, process/run or coil/heat ID, sensor/instrument ID, measured value, and
  (frequently) a position-along-strip or length-along-coil coordinate. This is the
  strongest justification in this research for a TimescaleDB-shaped core: continuous or
  high-frequency sensor logs keyed to a process run, joined to a much lower-frequency
  "certified/final" record (the MTR-level chemistry and dimensional summary) that gets
  reported to the customer. A rubric should treat "raw process telemetry" and
  "certified/reported summary" as two tiers of the same lineage, not the same table.

---

## Delta Cluster 1: Semi-Finished Input (Ingot, Billet)

### Process description
- **Ingot**: molten steel is teemed (poured) into individual, reusable cast-iron molds
  and allowed to solidify as a discrete cast shape; ingots have no fixed cross-section
  standard, taper for mold release, and typically have a "hot top" (riser) that is
  trimmed off after solidification to remove shrinkage-cavity/segregation defects. Ingot
  casting is a **batch** process — one mold, one pour, one discrete unit.
- **Billet**: produced by **continuous casting** — molten steel flows continuously from
  a tundish through a water-cooled copper mold, withdrawn as a solidifying strand,
  passes through a secondary spray-cooling zone, and is cut to length (torch-cut or
  shear) at the end of the caster. Continuous casting is a **continuous, in-line**
  process producing many discrete billet pieces from one heat.
- **Confirming the reconciliation's expected thin delta**: research supports treating
  Ingot vs. Billet as a genuinely thin delta at the *data-shape* level (both are "cast,
  unworked, no rolling-direction grain yet" semi-finished shapes with heat/chemistry as
  the dominant data), but the **process telemetry differs meaningfully**: ingot casting
  is a discrete-batch process (per-pour records: mold ID, pour temperature, pour time,
  hot-top trim weight) while billet casting is continuous-process telemetry (mold-level
  sensor readings, strand speed, secondary-cooling water flow, cut-length events) — so
  while the *certified/reported* data shape (chemistry + rough dimensions + heat number)
  is nearly identical, the *raw sensor telemetry* shape is not. A rubric should model
  this as one cluster with a "casting mode" attribute (batch vs. continuous) governing
  which telemetry sub-schema applies, rather than fully collapsing the two.
- Ingot casting is increasingly rare for bulk commercial steel (continuous casting
  dominates >90% of modern steel production by most industry accounts) but remains
  relevant for premium/aerospace-grade alloy steel via ingot-to-forging routes — worth
  noting for scoping a client's likely process mix rather than assuming ingot = legacy/
  irrelevant.

### Sensors and measurements
- **Mold-level sensors** (radioactive or electromagnetic) on continuous casters, holding
  level within roughly ±2 mm of setpoint, sampling in the tens-of-Hz range (search
  results indicate ~50–100 Hz sampling is realistic for transient mold-level events such
  as stopper-rod lag, submerged-entry-nozzle clogging, and argon-bubble discharge — but
  exact sampling rate is caster/vendor-specific and should be treated as an order-of-
  magnitude estimate, not a fixed spec).
- **Secondary cooling water flow/pressure/temperature** by cooling zone, controlling
  strand surface temperature and solidification rate; directly affects internal
  structure and downstream rollability.
- **Pyrometer-based surface temperature** readings along the strand.
- **Strand/casting speed** (continuous casting) or **pour rate/pour temperature**
  (ingot).
- **Cut-length / piece-count events** at the torch-cut or shear station (continuous
  casting) — each event effectively mints a new billet-piece ID under the parent heat.
- Internal-quality inspection (not always 100%-inline): ultrasonic examination for
  internal soundness/segregation is referenced under ASTM A388/A388M for forgings and
  analogous UT practices are applied to billet for forging-quality applications — likely
  sampled/periodic rather than continuous inline for standard commercial billet, though
  this specific inspection cadence is **not independently confirmed** and should be
  treated as uncertain.

### Data frequency/volume
- Continuous-casting telemetry (mold level, cooling flow, strand speed, temperature) is
  realistically **near-continuous / sub-second to low-Hz** during an active cast — this
  is consistent with the time-series/TimescaleDB shape flagged in the Core profile.
  Precise Hz figures vary by caster vendor and were not independently verified beyond
  the ~50–100 Hz mold-level figure found in search results; treat other rates as
  order-of-magnitude estimates pending client-specific confirmation.
- Certified/reported data (heat chemistry, billet dimensions, piece count/weight) is
  **per-heat and per-piece**, i.e., low-frequency relative to the sensor telemetry — a
  handful to low hundreds of records per heat, not a streaming volume.

### Quality tolerances
- No single ASTM standard governs generic commercial-billet cross-section dimensional
  tolerance the way A6/A6M does for structural plate/shapes — billet dimensional
  tolerance appears to be governed largely by **mill-specific/mill-association practice
  and customer PO** rather than one universal ASTM number; this should be flagged as
  **uncertain/needs client-specific confirmation** rather than asserted.
- Where billet/bloom is destined for aerospace/premium forging use, **ASTM A646/A646M**
  ("Premium Quality Alloy Steel Blooms and Billets for Aircraft and Aerospace
  Forgings") is a verified, applicable standard — but this is a premium-tier spec, not
  representative of general commercial/structural billet.
- Chemistry tolerance follows the governing grade specification's heat/check-analysis
  tables (see Core Profile item 2) — e.g., ASTM A29/A29M for carbon/alloy bar-grade
  chemistry, which is frequently the governing spec for billet destined to become bar.
- Internal-quality criteria (center segregation, porosity, internal cracks) are
  typically qualitative/visual plus periodic UT rather than a universal quantitative
  ASTM tolerance table for commercial billet — flagged as uncertain in the general case.

### Regulatory/traceability requirements
- Heat number traceability (Core Profile item 1) is the dominant traceability mechanism
  — billet pieces cut from a continuous cast are typically sequence-numbered within the
  heat (e.g., heat + cast-sequence + piece number) to preserve position-in-cast
  information, since defects can correlate with position in the cast sequence (start-of-
  cast and end-of-cast pieces carry different risk profiles than mid-cast pieces in
  general continuous-casting practice).
- MTR/certification per the governing downstream product spec (billet itself is rarely
  the final certified product — certification usually rides with the grade spec of
  whatever it's rolled into, e.g., A29/A29M for bar-destined billet), consistent with
  the Core Profile's caution against assuming one universal MTR schema.

---

## Delta Cluster 2: Flat Mill Products (Sheet, Plate, Coil — Hot-Roll & Cold-Roll)

Per Source 1's own normalization note, this is treated as **one** delta cluster,
differentiated internally by a thickness threshold (~0.187 in / 4.75 mm — plate vs.
sheet) and by coiled-vs-cut-length continuity (coil vs. cut sheet/plate), with hot-roll
vs. cold-roll as a **process attribute**, not a separate form factor.

### Process description
- **Hot rolling**: reheated slab is rolled above the recrystallization temperature
  through successive stands to progressively reduce thickness, producing hot-rolled
  sheet/strip/plate; the strip is coiled at the run-out table (coiling temperature is a
  controlled process variable affecting final mechanical properties).
- **Cold rolling**: hot-rolled, pickled coil is further reduced at room temperature
  through a cold mill (commonly a multi-stand tandem mill), increasing strength/
  hardness and improving surface finish/gauge precision beyond what hot rolling alone
  achieves; frequently followed by annealing and temper (skin-pass) rolling to restore
  formability.
- **Pickling**: an inline or batch acid-bath step between hot rolling and cold rolling
  that removes mill scale — relevant to the automotive coil-steel / Pickle-and-Oil (P&O)
  example: a P&O line pickles hot-rolled coil and applies a thin oil film for corrosion
  protection prior to shipment to a stamper, without necessarily performing the full
  cold-reduction step. This confirms P&O as a legitimate, distinct process step worth
  its own data shape (chemical bath parameters, line speed, oil film weight) sitting
  between hot-roll and cold-roll/coating in the process chain, not merely a footnote.
- **Coating** (galvanizing/galvannealing, when applicable): hot-dip zinc or zinc-iron
  coating applied to cleaned coil, directly relevant to the automotive body-panel supply
  chain example.
- Coil, sheet, and plate are dimensional/continuity outputs of the same rolling
  process family, not different material inputs — confirming Source 1's normalization
  guidance.

### Sensors and measurements
- **X-ray thickness/gauge sensors**: the verified, standard inline technology for
  gauge control on both hot and cold mills — search results confirm multi-position
  deployment (entry-side, interstand, exit-side) with feedback (gauge control via gap,
  "GBG") and feedforward ("GFG") control loops referencing the x-ray gauge signal.
- **Tension control** (entry/exit strip tension, often torque-regulated — "TCT" per
  search results) — critical on cold mills where thin-gauge strip is prone to breaks/
  wrinkling under improper tension.
- **Coiling temperature** sensors (pyrometers) at the hot-mill run-out table — a
  first-order variable for final mechanical properties (grain structure).
- **Coating weight** measurement (for galvanized/galvannealed product) — verified
  standard practice is the **triple-spot test (TST)** under ASTM A924/A924M, sampling
  at edge-center-edge positions across the coated sheet, both sides.
- **Flatness/shape** sensors (shapemeter rolls) on cold mills, and **width** measurement
  (typically optical/laser).
- **Surface inspection** (optical, often automated defect-detection cameras) for
  scale, pits, scratches, coating defects.

### Data frequency/volume
- Gauge, tension, and temperature control loops on a running mill are inherently
  **continuous, high-rate control-loop data** (industrial control systems in this space
  commonly log at rates from roughly 1 Hz up to high tens/hundreds of Hz depending on
  the specific loop and vendor — search results did not surface a single authoritative
  figure for strip mills specifically, so treat any specific Hz figure here as an
  estimate, not a verified spec).
- Coating-weight TST is a **per-coil sampling** measurement (edge-center-edge spot
  samples), not continuous — this is a lower-frequency, per-coil certified data point
  layered on top of continuous process telemetry, again matching the Core Profile's
  "raw telemetry vs. certified summary" two-tier pattern.
- Final certified record granularity is typically **per coil** (or per cut sheet/plate
  bundle), with the coil ID as the primary key tying back to the heat number.

### Quality tolerances
- **ASTM A1011/A1011M** — verified standard for hot-rolled carbon/structural/HSLA sheet
  and strip, coil and cut length, up to 0.230 in (6 mm) thickness; covers chemistry and
  tensile-property requirements by grade (CS, SS, HSLAS, HSLAS-F, UHSS).
- **ASTM A1008/A1008M** — verified standard for cold-rolled carbon/structural/HSLA
  sheet, coil and cut length; typical commercial thickness range roughly 0.20–5.0 mm,
  width roughly 600–2000 mm per trade sources (mill-capability-dependent, not a fixed
  ASTM number — treat as typical/representative, not a hard spec limit).
- **ASTM A6/A6M** — verified general-requirements standard governing plate (and other
  structural product forms) dimensional tolerances (thickness, length, width,
  flatness/camber) and certification/marking requirements; underpins many downstream
  plate grade specs (A36/A36M, A572/A572M, A709/A709M, etc.).
- **ASTM A653/A653M** — verified standard for hot-dip zinc-coated (galvanized) or
  zinc-iron-coated (galvannealed) sheet; coating designations (G30/G40/G60/G90/G115 in
  inch-pound units) specify minimum coating weight per ASTM A924/A924M's triple-spot
  test methodology, including a same-side minimum (no less than 40% of the single-spot
  requirement on either individual side) to guard against badly imbalanced coating
  between the two faces.
- The sheet/plate dividing line (~0.187 in / 4.75 mm, per Source 1) is a trade/
  reference-table convention rather than a single ASTM clause number identified in this
  research pass — flagged as a convention to confirm against the specific grade spec in
  use for a given client (A1011 itself covers "up to 0.230 in," which does not map
  cleanly 1:1 onto the 0.187 in trade threshold — worth resolving explicitly in the
  rubric rather than treating the two thresholds as interchangeable).

### Regulatory/traceability requirements
- Coil-level heat traceability (coil ID → heat number) is standard; within the P&O/
  automotive example, traceability commonly needs to survive multiple ownership/
  processing hand-offs (mill → P&O processor → stamper), which is a good concrete
  anchor for the Core Profile's "traceability breaks at hand-offs" risk.
- MTR/certification per the governing product spec (A1011, A1008, A653, etc.); EN 10204
  types apply if the customer/PO requires them (common in automotive and industrial
  procurement, per Core Profile item 3).

---

## Delta Cluster 3: Long Mill Products (Bar, Rod, Wire)

Round stock and hex stock are cross-section-shape variants of Bar (a Core/cluster-level
attribute field, not a separate delta). Rod and Bar are a genuine operational
distinction (coiled vs. cut-length) frequently conflated in vendor data.

### Process description
- **Bar** (round/square/flat/hex cross-section): hot-rolled from billet through a bar
  mill's roughing/intermediate/finishing stands, then either cut to length (hot-rolled
  bar) or further cold-finished (cold-drawn/cold-finished bar, per ASTM A108-type
  practice, referenced from A29/A29M) for tighter dimensional tolerance and improved
  surface finish. Bar is a **cut-length, non-coiled** product.
- **Rod**: hot-rolled from billet through a rod mill, finishing at high speed through a
  finishing block, then formed into coils via a laying head and cooled on a conveyor
  (Stelmor-type controlled cooling is common industry practice for controlling
  microstructure). Rod is fundamentally a **coiled, continuous** product — this is the
  operational distinction from bar that the reconciliation flagged as a real
  data-quality risk: vendor/trade data frequently uses "rod" and "bar" loosely
  (especially for small round cross-sections), but a rod's process/data shape
  (coil ID, coil weight, wrap/lap count) is structurally different from a cut-length
  bar's (piece count, bundle ID, cut length per piece).
- **Wire**: drawn from rod stock by pulling through progressively smaller dies (cold
  drawing), reducing cross-section and elongating the material; drawn in one or more
  passes depending on total reduction needed, then typically re-coiled onto reels/spools.

### Sensors and measurements
- **Bar/rod dimensional gauging**: diameter/cross-section laser or optical gauges
  inline on the finishing stands; straightness measurement (particularly relevant to
  cut-length bar).
- **Rod coiling**: laying-head speed, coil weight, wrap count/lap monitoring at the
  reforming station; Stelmor conveyor cooling-rate control (fan zone temperature/
  airflow) where controlled cooling is used.
- **Wire drawing**: **draw force** per die/per pass (verified: drawing force is
  commonly on the order of ~60% of the wire's ultimate tensile strength in practice,
  combining plastic-deformation force and die-friction force; this is a representative
  figure from general wire-drawing literature, not a fixed spec for all steel wire
  grades), **die/wire temperature**, **drawing speed**, and **reduction of area per
  pass** (search-verified typical ranges: roughly 15–25% area reduction per pass for
  fine wire, roughly 20–45% for larger sizes — total elongation/reduction is a
  cumulative multi-pass figure). Note: the research explicitly found that **systematic,
  commercialized inline process monitoring of wire drawing is comparatively immature**
  compared to flat-rolling gauge control — search results describe drawing-process
  monitoring as "rare" in current industrial practice, meaning per-die/per-pass
  telemetry may exist as isolated line-controller setpoints rather than as a
  well-instrumented continuous data stream in many wire mills. This is a notable
  finding for rubric design: don't assume the same sensor-density expectations for
  wire drawing that apply to flat-rolling.
- **Mechanical test sampling**: tensile test (yield/tensile strength, elongation,
  reduction of area) and bend test, typically per-lot/per-coil sample rather than
  continuous.

### Data frequency/volume
- Rolling-mill dimensional gauging (bar, rod) is continuous/inline at mill speed,
  broadly comparable in character to the flat-mill gauge-control loops in Cluster 2,
  though specific Hz figures were not independently verified for bar/rod mills in this
  research pass and should be treated as estimates.
- Wire-drawing telemetry, per the finding above, is more likely to be **per-pass /
  per-die setpoint records** rather than continuous high-frequency sensor logging in a
  typical (non-cutting-edge) mill — a meaningfully different data-volume profile than
  Clusters 1 and 2.
- Mechanical test data (tensile/bend) is **per-lot/per-heat sampling**, low frequency,
  consistent with the Core Profile's certified-summary tier.

### Quality tolerances
- **ASTM A29/A29M** — verified general-requirements standard for hot-wrought carbon and
  alloy steel bars, covering heat/check-analysis chemistry tolerance tables; cold-
  finished bar dimensional tolerances are now housed in **ASTM A108** per current A29/
  A29M scope notes (a cross-reference worth confirming directly against A108 in a later
  pass — not independently pulled in this research).
- **ASTM A510/A510M** — verified general-requirements standard for carbon (and alloy,
  in later revisions) steel wire rod and coarse round wire, coils or straightened/cut
  lengths — covers chemistry and, where specified, grain size.
- Wire-specific dimensional/mechanical standards (gauge tolerance, tensile grade
  tables) are governed by product-specific wire specs layered on top of A510's general
  requirements (e.g., mechanical-fastener wire, spring wire, or prestressing wire each
  have their own ASTM spec); this research did not pull a single "general wire"
  dimensional-tolerance standard analogous to A6/A6M for plate — flagged as an area
  needing narrower confirmation once a client's specific wire end-use is known.
- Hex/round/square/flat bar cross-section tolerances are governed by the same A29/A29M
  general-requirements framework, with cross-section shape as a distinguishing
  attribute rather than a separate standard.

### Regulatory/traceability requirements
- Heat traceability as per Core Profile; bar is typically bundle/lot-tagged at cut
  length, rod and wire are coil/reel-tagged — again reinforcing the coiled-vs-cut-length
  distinction as a schema-relevant attribute (bundle-of-pieces vs. single continuous
  coil changes what "one traceable unit" means).
- MTR/certification per governing bar or wire-rod spec (A29/A29M, A510/A510M, or a
  narrower downstream spec).

---

## Delta Cluster 4: Tubular (Pipe — Semi-Finished/Unfinished Stock Only)

Distinct from the other three clusters — seam-weld inspection and OD/wall-thickness
data have no direct analog elsewhere in this research.

### Process description
- **Seamless pipe**: a solid round billet is pierced (e.g., rotary/Mannesmann piercing)
  to form a hollow shell, then elongated/sized through further rolling to final OD and
  wall thickness — no weld seam exists.
- **Welded pipe**: flat strip/skelp (from coil, i.e., a direct downstream consumer of
  Cluster 2 output) is roll-formed into a tube shape and the longitudinal (or helical/
  spiral) seam is welded closed (commonly ERW — electric resistance welding, or
  submerged-arc welding for larger-diameter/heavier-wall pipe), then typically sized
  and may be heat-treated.
- This confirms an explicit process-level overlap: welded-pipe production directly
  consumes Cluster 2 (flat/coil) output as its feedstock — a genuine upstream/downstream
  relationship, not just a data-shape similarity (see Overlaps section).

### Sensors and measurements
- **OD (outside diameter)** measurement, typically inline laser/optical gauging.
- **Wall thickness** measurement, commonly ultrasonic inline gauging (and manual/spot
  UT verification).
- **Seam weld inspection** (welded pipe only): **ultrasonic testing (UT)** — verified as
  used for full/100% volumetric inspection of the weld seam and pipe body on API 5L and
  critical-service pipe; **eddy current testing (ET)** — verified as used for rapid
  online surface/near-surface inspection; radiographic testing (RT) and magnetic
  particle testing (MT) are also referenced as inspection methods in the broader
  pipe-inspection literature, applicable depending on service class and spec.
- **Hydrostatic test**: verified as a required, typically 100%, per-length pressure
  test on line pipe (API 5L references hydrostatic testing at a multiple, commonly
  cited as 1.5x design pressure, of the pipe's rated pressure — treat the specific 1.5x
  multiplier as representative/commonly-cited rather than independently confirmed
  against the current API 5L edition text).
- **Chemistry/mechanical sampling** as per Core Profile, tied to the feedstock heat
  (billet for seamless, coil/skelp heat for welded).

### Data frequency/volume
- OD and wall-thickness gauging is continuous/inline at mill speed during pipe forming
  and sizing — comparable in character to flat-mill gauge control (Cluster 2).
- UT/ET seam inspection is inline and effectively continuous along the weld seam for
  100%-inspected product (a meaningfully higher inspection-coverage expectation than
  the sampled/periodic UT noted for billet internal quality in Cluster 1 — worth
  flagging as a real difference in inspection intensity between clusters, not an
  oversight).
- Hydrostatic test is a discrete **per-length/per-joint event** (pass/fail plus
  pressure-vs-time trace), not continuous streaming data — another example of the
  Core Profile's "continuous telemetry vs. discrete certified event" pattern, with the
  hydro test itself being a good example of a *discrete but still time-series-shaped*
  event (a pressure-vs-time curve per test).

### Quality tolerances
- **ASTM A53** — verified standard covering both welded and seamless carbon steel pipe,
  general applications (mechanical/pressure/plumbing); notably wide wall-thickness
  tolerance, search-confirmed at roughly **-12.5%** of nominal wall thickness minimum
  (i.e., minimum wall must not fall more than 12.5% under nominal at any point) with
  general trade sourcing suggesting a symmetric ±12.5% framing is commonly cited,
  though the verified figure is specifically the minimum-wall (-12.5%) requirement.
- **ASTM A106** — verified standard for seamless carbon steel pipe for high-temperature
  service; adopts the same -12.5% minimum-wall-thickness permissible variation
  (referencing ASTM A530's general pipe-dimension tolerance practice per search
  results), with an industry-cited (not independently confirmed against the standard
  text itself) OD tolerance around ±1%.
- **API 5L** — verified as the governing line-pipe specification with its own
  seamless/welded thickness-tolerance tables (PSL 1 / PSL 2 product specification
  levels); this research did not pull the exact numeric tolerance tables for API 5L
  and treats them as **unverified pending a direct standard-text pull** — API 5L
  tolerances are known to differ from A53/A106 but the specific percentages should not
  be asserted without confirming against the actual standard (currently 46th edition
  per trade sources, itself unverified against API directly).
- Rebar (ASTM A615/A706 etc.) is explicitly **out of scope** here since it's a finished/
  structural product not in Brian's original list or this cluster's remit — noted only
  to avoid confusion since Source 1 grouped rebar under "Tubular & Structural."

### Regulatory/traceability requirements
- Heat traceability per Core Profile, with the added wrinkle that welded pipe's
  traceability chain must span two upstream heats in effect (the coil/skelp heat and,
  indirectly, whatever billet produced that coil) if full genealogy is required —
  another concrete instance of the multi-hop traceability risk flagged in the Core
  Profile.
- Weld-seam inspection records (UT/ET pass-fail, and defect-location data when
  applicable) are a traceability record type with no analog in the other three
  clusters — should be modeled as pipe-specific in the rubric, not folded into the
  generic dimensional-tolerance record.
- MTR/certification per API 5L and/or ASTM A53/A106 depending on end use; EN 10204 3.1
  is common for oil-and-gas-bound pipe per this research (consistent with Core Profile
  item 3's note that 3.1 is especially common in pressure/oil-and-gas procurement).

---

## Black Iron — Open Question

**Working hypothesis (needs Brian's confirmation before folding into the schema):**
General steel-trade usage search-confirms "black iron" refers to **uncoated,
mill-finish carbon steel pipe** — the "black" describes the dark iron-oxide (mill
scale) surface left by hot rolling, in contrast to zinc-coated ("galvanized") pipe. On
this evidence, black iron is a **coating/finish status attribute** (uncoated/mill-finish
vs. galvanized vs. other coating), most directly applicable within the **Tubular
(pipe)** cluster, and by extension could apply as a general finish-status attribute
anywhere a coating decision exists (also relevant to Cluster 2's flat products, which
have their own coated/uncoated distinction via A1011 "as-rolled" vs. A653 galvanized).

This research found **no evidence supporting "black iron" as a standalone geometric
form factor** — nothing in trade or standards sourcing treats it as a distinct product
shape/dimension category the way, say, "billet" or "pipe" are. The evidence supports
folding it into the Core Profile (or a cluster-level attribute) as a **finish/coating-
status field** rather than retaining it as a 5th delta cluster.

**Still open and unverified:** whether Brian's original "black iron (rolled steel
variant)" framing refers specifically to pipe (most consistent with trade usage found
here), or to a broader rolled-steel product line his hauling experience associates
with a specific finish/product name locally — this nuance was not resolved by this
research pass and should be confirmed directly with Brian rather than assumed.

---

## Overlaps & Shared Data Shapes

- **Semi-Finished Input ↔ all downstream clusters**: every downstream cluster's core
  chemistry and heat-traceability data *originates* at this stage — this isn't really
  an "overlap" so much as a strict upstream dependency. Roughly the entire Core Data
  Profile (heat number, chemistry, unit-of-sale weight basis) is *established* here and
  *inherited* everywhere else, which is why the Core/Delta split works cleanly for this
  cluster: very little of Semi-Finished Input's data is genuinely unique beyond the
  casting-process telemetry itself (mold level, secondary cooling, cast-sequence
  position). Rough estimate: the majority of what could be described as "billet/ingot
  data" is actually Core-Profile data; the delta specific to this cluster is closer to
  the casting telemetry alone.
- **Flat Mill Products ↔ Tubular**: a **direct process dependency**, not just a shape
  overlap — welded pipe's feedstock (skelp/strip) *is* Cluster 2 output. A rubric
  covering a client who does both should expect to see Cluster 2's coil-level
  certified data show up as an input record inside Cluster 4's traceability chain.
- **Long Mill Products' internal overlap (Bar vs. Rod)**: confirmed as a **genuine, not
  merely nominal, operational distinction** (coiled vs. cut-length changes the
  traceability unit, the inline sensor set, and the finishing route), but they share
  nearly all upstream process description (both roll from billet through a bar/rod mill)
  and the same general-requirements chemistry standard family is adjacent (A29/A29M for
  bar, A510/A510M for rod — separate standards, same committee lineage). The
  reconciliation's caution about vendor data conflating "rod" and "bar" is
  well-founded — this is a real, evidenced data-quality risk (small-diameter coiled rod
  and small-diameter cut bar are visually and colloquially easy to conflate in
  non-technical sourcing/vendor data) worth its own rubric check, distinct from the
  legitimate process/data-shape delta between them.
- **Wire ↔ Long Mill Products' rod**: wire is a direct downstream consumer of rod
  (drawn from rod stock), the same upstream-dependency pattern seen between Flat Mill
  Products and Tubular — not a coincidence, but a structural feature of how mill
  products chain into each other. A rubric could reasonably model an explicit
  "feedstock source cluster" relationship rather than treating all four clusters as
  siblings with no inter-dependency.
- **Coating-weight data shape (Flat Mill Products' galvanizing vs. Tubular's black-
  iron/galvanized status)**: both clusters have a coating-related attribute, but they
  are evidenced at different rigor levels — Flat Mill Products has a verified,
  quantitative standard (A653/A924 triple-spot test, numeric coating-weight
  designations), while Tubular's coated/uncoated distinction (per the Black Iron
  section) appears to be more of a qualitative status flag in general trade usage
  without an equally rigorous quantitative test standard surfaced in this research —
  worth confirming whether pipe galvanizing follows A653-family coating-weight testing
  or a separate pipe-specific coating spec before assuming parity between the two.
- **Cross-cluster telemetry pattern**: every cluster exhibits the same two-tier "raw
  continuous/near-continuous process telemetry" vs. "per-piece/per-coil/per-heat
  certified summary" data shape (explicitly noted per-cluster above). This is the
  single strongest cross-cluster structural finding of this research and is likely the
  most important shared pattern for rubric/schema design — it recurs in all four
  clusters and in the Core Profile, and argues for a generic two-tier schema pattern
  (time-series telemetry table + certified-record table, joined by run/coil/heat ID)
  rather than cluster-specific one-off designs.
