# Distribution-level connection application — what the developer submits

For projects connecting via a **Distribution Network Operator (DNO)** — the company that owns the lower-voltage local network. Governed by the **Distribution Code (DCode)**, **Engineering Recommendation G99** for generation (and **G98** for the smallest microgenerators), and **DCUSA** for the commercial side.

The form differs by project type — sections below cover Generation, Demand, Storage, and Mixed / Co-located.

---

## 1. Generation

Pathway and form depend on the project's G99 **Type**: A is the smallest (≤1 MW), B is 1–10 MW, C is 10–50 MW, D is ≥50 MW or transmission-connected.

| Category | What the developer submits | Why the DNO needs it | Source |
| --- | --- | --- | --- |
| Applicant | Customer name, address, agent / installer details | Identifies counterparty and point of contact | G99 Design Phase |
| Site plan | Scaled plan showing buildings, roads, boundary, and proposed substation location | DNO needs to know what's there before quoting design and cost | G99 Design Phase; DCode DPC §6 |
| Connection point | Proposed metering location + maximum capacity (kVA) at each point | Defines where the meter goes and how much power can flow | G99 Design Phase |
| Project type | G99 classification — Type A (≤1 MW), Type B (1–10 MW), Type C (10–50 MW), Type D (≥50 MW or TX-connected) | Sets which application pathway, form, and tests apply | G99 §2.2 |
| Technology | Fuel / technology — solar PV, wind, battery, CHP, etc. — and how it interfaces with the network | Determines control and protection requirements | G99 Standard / Fast-Track SGI-1/2/3 |
| Type-test evidence | Manufacturer certification that the unit passes the relevant type test (G98 for the smallest, G99 above) | Confirms the equipment is approved for use on a UK distribution network | G99 Construction Phase; DCode DPC §7 |
| PGMD *(Type B/C/D)* | Power Generating Module Document — compliance statement + full technical data sheet | Single document evidencing the unit meets every G99 criterion | G99 Construction Phase |
| Protection & islanding | Settings for the relays + the anti-islanding scheme | Critical for safety of DNO field staff during faults | G99 §16–19 |
| Performance data | Efficiency curves, active / reactive power control range, voltage-control capability | DNO uses this to design the local network around your kit | G99 Annex C |
| Network impact study | Output of any impact assessment / feasibility study (where size requires it) | Identifies reinforcement need or curtailed-export terms | G99 Fast-Track / Standard pathway |
| Installation form | Form A1-1 / A1-2 (Type A) or Standard Application Form (Type B/C/D) | The DNO's permission slip — pre-installation for Type B+, post-installation notification for some Type A | G99 Forms A1-1, A1-2, A3-1, A3-2 |
| Commissioning tests | Test results — Type A: A3-1 / A3-2; Type B/C: Form B3 / C3 + interface-protection test report | Proves the kit actually behaves on site as it did in the factory | G99 §16–19 |
| Operational Notifications *(B/C/D)* | EON (Energisation), ION (Interim), FON (Final) — three sequential sign-offs | Lets the DNO release energisation in stages | G99 Operational Notifications |
| Land & planning | Evidence of right to occupy + any planning consent | Same purpose as transmission, scaled down | DCode DPC §6 |

---

## 2. Demand (load)

Pure load connecting via a DNO — homes, businesses, factories, distribution-connected data centres. Governed by the **Distribution Code DPC sections** and the DNO's own **Connection Charging Methodology**. Embedded demand sits **outside** the Gate 2 Criteria Methodology today.

No G98 / G99 type-testing is required for a pure load. Form complexity scales with **connection voltage** (LV / HV / EHV) and **maximum demand** (kVA), not with G99 Types.

| Category | What the developer submits | Why the DNO needs it | Source |
| --- | --- | --- | --- |
| Applicant | Customer name, address, agent / installer details | Identifies counterparty | DCode DPC §6 |
| Site plan | Scaled site plan showing buildings, the proposed point of connection, and any existing supply | Lets DNO size the cable, transformer, and switchgear | DCode DPC §6 |
| Premises type | Use class — domestic, commercial, industrial, data centre, EV charging, hospital, etc. | Sets reliability tier expectations and informs network protection design | DCode DPC §6 |
| Maximum demand | Peak demand (kVA) — single value for small jobs, profile (24-hour, seasonal) for larger ones | Sizes the connection; triggers reinforcement studies above a DNO-set threshold | DCode DPC §6 |
| Diversity factor | Diversity / coincidence factor for multi-load sites (residential developments, commercial parks) | Avoids over-sizing the connection | DCode DPC §6 |
| Load characteristics | Power factor, motor-starting kVA, harmonic / flicker emissions, large-load step changes | Lets the DNO size voltage support and protection | DCode DPC §6 / DOC |
| Connection voltage requested | LV (≤1 kV), HV (1 kV – 22 kV), or EHV (33 kV+) | Drives the Guaranteed Standards of Performance deadline (45 wd LV / 65 wd HV/EHV) | DCode DPC §6 |
| On-site generation / storage | Declaration of any G98 / G99 generators or BESS on the same site (even if not exporting) | Affects net import profile, fault contribution, and protection grading | G99 §2 (cross-reference) |
| Sensitive-load flag | Identification of life-safety, hospital, defence, or data-centre critical loads | Triggers higher reliability requirements | DCode DPC §6 |
| Land & planning | Right to occupy + planning consent (especially for data centres and large industrial) | Filters speculative applications; reform proposes formal readiness tests | Demand Connections CFI Feb 2026 §5.28 |
| Phased / interruptible *(emerging)* | Willingness to accept a phased build-up or non-firm / time-of-connection terms | Faster offer date for loads that can flex | CFI Feb 2026 §5.36 (Connect) |
| Charging methodology data | Information needed for the DNO's Connection Charging Methodology — shallow vs deep cost share | Drives the connection charge the customer ultimately pays | DCUSA Schedules |

Notes:

- DX demand queue stood at 29 GW in June 2025.
- For large data-centre demand at distribution voltage, DNOs are starting to ask for outline / full planning consent at application stage — mirroring the strengthening at transmission. Ofgem's Feb 2026 CFI explicitly opens whether to formalise this.

---

## 3. Storage

Battery energy storage connecting at distribution voltage. Treated as a **generator under G99** for technical purposes (it can export). From **1 March 2026**, ER G99 Issue 2 introduces explicit storage-specific clauses for "Power Generating Modules incorporating Electricity Storage". Most DNO storage applications follow the standard G99 Type pathway.

**Same data as Generation, plus the storage-specific fields below.**

| Category | Storage-specific addition | Why the DNO needs it | Source |
| --- | --- | --- | --- |
| Energy capacity | Energy storage capacity (MWh) and rated duration (hours at full power) | Distinguishes 1-h, 2-h, 4-h, long-duration assets | G99 (PGM with Electricity Storage) |
| Charge / discharge | Maximum charge rate (kW / MW import) and maximum discharge rate (kW / MW export); whether equal or asymmetric | Sizes the bidirectional connection | G99 §2.2 (registered capacity) |
| Import + export capacity | Both **import** capacity and **export** capacity declared on the application | Network treats the asset as both load and generator; charging methodology may differ for import side | DCUSA |
| Threshold check | Confirmation that export per phase exceeds 3.68 kW (the G99 trigger threshold) — below that it falls under G98 fit-and-inform | Determines whether G99 application or G98 notification applies | G99 / G98 split (16 A per phase) |
| Anti-islanding (storage-specific) | Anti-islanding settings appropriate to a bidirectional asset; protection co-ordination with on-site generation if any | Storage has more complex islanding behaviour than a passive generator | G99 §16–19 (Issue 2 storage clauses, in force 1 Mar 2026) |
| Grid-forming declaration | Whether the inverter is grid-following (default) or grid-forming | Grid-forming behaviour is increasingly valued; affects fault-level contribution | G99 Issue 2 (Mar 2025) |
| Frequency-response capability | Static frequency response, dynamic frequency response (DM, DR, DC envelopes), virtual inertia if grid-forming | Lets the DNO and downstream system operator value the asset's contribution | G99 (Issue 2 storage) |

---

## 4. Mixed / Co-located

Sites combining generation, storage, and / or demand on a single distribution connection — typically solar PV + BESS, sometimes with co-located demand.

| Category | What the developer submits | Why the DNO needs it | Source |
| --- | --- | --- | --- |
| Per-technology applications | One G99 application per generator / storage unit (each with its own Type and form set), plus a demand application for any pure load | Each technology has its own technical envelope; the DNO assesses them individually | G99 §2.2; DCode DPC §6 |
| Combined site capacities | Firm export capacity (the maximum the whole site can ever export) and total import capacity | The shared connection asset is sized for the combined limit, not the sum of the parts | DCUSA capacity registration |
| Site dispatch logic | How the technologies share the connection — priority rules, curtailment order, BESS charge / discharge logic, demand-response behaviour | Drives what the DNO can rely on for protection grading and active network management signalling | NESO Co-location Guidance (technical principles) |
| Storage flow declaration | BESS declared as import-only, export-only, or import + export (and whether it can charge from the grid or only from co-located generation) | Affects how it counts against export capacity and what charging methodology applies | G99; DCUSA |
| Curtailment / flexible-connection terms | Acceptance of an active network management contract (curtailment in exchange for early connection) | Lets the DNO offer an earlier date in lieu of full reinforcement | DCode DPC §6 (flexible) |
| Sequenced commissioning plan | Order in which technologies will be commissioned and the EON / ION / FON sequence for each | Lets the DNO stage energisation safely and confirm interim limits | G99 Operational Notifications |
| Substantial modifications | Future plans to add storage / generation / demand to an existing connection — handled as a modification, not a fresh application | Triggers re-assessment of the affected unit, not a full re-application | NESO Co-location Appendix B (worked examples) |

Notes:

- Most distribution-level co-located projects today are solar PV + BESS, with the BESS often configured as charge-from-PV-only to qualify for a single export-only commercial registration.

---

## Primary sources

- **Distribution Code (DCode)** — version 58, Energy Networks Association.
- **DCUSA** (Distribution Connection and Use of System Agreement) — version 18.1.
- **Engineering Recommendation G99** — guidance document, ENA, January 2023; Issue 2 effective 1 March 2026 for storage clauses.
- **Engineering Recommendation G98** — for fit-and-inform microgeneration installations.
- **NESO Guidance Notes for Co-location of Different Technologies, Issue 3.1** — June 2025 (technical principles cascade to distribution practice).
- **Demand Connections Reform — Call for Input** — Ofgem, 13 February 2026.
