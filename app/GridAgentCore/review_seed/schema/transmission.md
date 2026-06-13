# Transmission-level connection application — what the developer submits

For projects connecting directly to the GB transmission system. Routed via NESO (the system operator) under the **Connection and Use of System Code (CUSC)**, with technical data set by the **Grid Code**. Post-reform, the queue position depends on passing the **Gate 2 Criteria Methodology**.

The form differs by project type — sections below cover Generation, Demand, Storage, and Mixed / Co-located.

---

## 1. Generation

| Category | What the developer submits | Why the network needs it | Source |
| --- | --- | --- | --- |
| Site & location | Site address + GPS coordinates (WGS84, 3 d.p.) | Pinpoints where on the network you want to connect | Gate 2 Criteria Methodology §4.1b |
| Land — area | Red-line boundary plan (scaled drawing of your site outline, with postcode and key) | Proves the site is big enough for the technology and capacity claimed | CUSC §17.7; Gate 2 §4.1b |
| Land — control | Evidence of land rights — freehold, lease, or option agreement of at least 20 years | Stops speculative applications from people who don't actually have the land | Gate 2 §4.1c |
| Land — density | Compliance with Ofgem's "Energy Density" minimum acreage table for your technology | Same purpose: filter speculative applications by ensuring enough land for the claimed capacity | Gate 2 §4.1a |
| Planning | Planning consent status — submitted, granted, or DCO (Development Consent Order, the route used for projects above 50 MW onshore / 100 MW offshore) | Establishes how close the project is to being build-ready | Gate 2 §5 |
| Project capacity | Megawatt capacity for each technology + total connection capacity requested | Drives network-impact studies and queue ordering | CUSC §2.2.4; Gate 2 §4.1b |
| Company | Corporate identity, ownership, financial standing | Makes sure the counterparty can actually pay and build | CUSC Schedule 2 Exhibit B; CUSC §2 Part III |
| Plant — basic | Generation type, fuel, efficiency, operating envelope | Used in network design and dispatch planning | Grid Code PC.A.3 |
| Plant — protection | Protection relay settings + fault-clearance times | Must align with the network's own protection so faults don't cascade | CUSC Appendix F4 |
| Plant — dynamic | Special automatic facilities — fast frequency response, voltage support, etc. | Tells NESO what you can offer the system in real-time stability events | CUSC Appendix F3 |
| Ancillary services | Generating-unit parameters, HVDC converter specs, power-park module data | Lets NESO model and procure system-stability services | CUSC §1.3.3 / Schedule 2 Exhibit 4 |
| Network studies | Steady-state load flow, fault-level analysis, transient stability assessment | Confirms the connection won't destabilise the rest of the grid | Grid Code Connection Conditions; CNDM Dec 2025 |
| Metering & access | Proposed metering point + requested transmission entry capacity (short-term vs long-duration) | Defines billing point and how much you can export at each timescale | CUSC §2.3; CUSC Appendix C |
| Environmental | Environmental Impact Assessment / Environmental Statement (where planning requires one) | Mostly a planning input but copied into the connection pack | Planning regulations; Gate 2 |

Notes:

- Post-TMO4+ reform, the Gate 2 filter is the dominant change: the pre-reform queue of ~739 GW was stripped to ~283 GW of generation/storage at Gate 2 in December 2025.
- The Connections Network Design Methodology (CNDM, Dec 2025) sets how NESO converts a portfolio of Gate 2 applications into a coordinated network design.

---

## 2. Demand (load)

Large loads connecting directly to the transmission system — most prominently data centres. Demand sits **outside** the Gate 2 generation/storage filter today; reform is being designed under Ofgem's *Demand Connections Reform* programme (Feb 2026 Call for Input). Post-Aug 2024, new directly-connected transmission demand applications receive a **Transitional Offer**.

| Category | What the developer submits | Why the network needs it | Source |
| --- | --- | --- | --- |
| Project & site | Site address + coordinates; site classification (data centre, industrial, electrification, hydrogen, etc.) | Identifies the load type and its operating profile | CUSC application schedule |
| Land — control | Exclusive land access (proposed Gate-2-style readiness criterion under reform) | Filters speculative demand applications, matching the generation regime | Demand Connections CFI Feb 2026 §5.2 |
| Planning | Outline or full planning consent (or evidence of submission) — proposed strengthened readiness criterion for data centres | Demonstrates the site can actually be built | CFI Feb 2026 §5.27 |
| Commercial | Commercial off-taker — for data centres, evidence of customer / hyperscaler tenancy contract | Demand-side equivalent of a generator's PPA — proves real economic backing | CFI Feb 2026 §5.2 |
| Project capacity | Maximum demand (MW) + minimum demand + import profile (24-hour, seasonal); for data centres, IT load curve and Power Usage Effectiveness (PUE) | Drives network-impact studies and reinforcement triggers | Grid Code Demand Code (DC) |
| Phased / ramped option | Willingness to accept a phased or ramped connection (build-up of capacity over time) | Lets NESO offer earlier access in exchange for staged ramp | CFI Feb 2026 §5.2 (Connect) |
| Non-firm option | Willingness to accept a non-firm or interruptible connection | Faster connection date for loads that can flex; reform actively encourages this for data centres | CFI Feb 2026 §5.2 (Connect) |
| Load characteristics | Power factor, motor-starting characteristics, harmonic emissions, voltage-flicker profile | Lets the TO size local protection, voltage support, and conductor specs | Grid Code DC.A |
| Sensitive-load flag | Identification of critical / sensitive loads (data centre racks, hospital, defence) | Drives reliability-tier expectations and back-up planning | Grid Code DC |
| Behind-the-meter generation | Declaration of any on-site standby / behind-the-meter generation (diesel, gas, BESS) and its operating mode | Affects net import profile and fault contribution | Grid Code DC.A |
| Securities | User commitment fee / financial security under CUSC Section 15 — currently higher upfront for demand than for generation | De-risks the network's reinforcement spend if the project doesn't progress | CUSC §15 User Commitment Methodology |
| Strategic fit *(emerging)* | Application to an AI Growth Zone or other strategically-prioritised plan (under reform) | Government / Ofgem are designing prioritisation mechanisms for strategic demand | CFI Feb 2026 §5.30 (Plan) |

Notes:

- The TX demand queue grew from 41 GW (Nov 2024) to 125 GW (Jun 2025) — about three times current GB peak demand of 45 GW. Data centres alone account for ~50 GW.
- Ofgem's Feb 2026 Call for Input is consulting on a financial mechanism for data centres — three options: refundable deposit, Progression Commitment Fee (mirroring the generation CMP448 PCF), or upfront non-refundable fee.

---

## 3. Storage

Battery and long-duration storage projects connecting at transmission voltage. Treated as **generation** for technical purposes under the Grid Code (it can export power), with extra fields to describe the bidirectional flow and the energy-storage characteristics. Subject to the same Gate 2 readiness filter as generation.

**Same data as Generation, plus the storage-specific fields below.**

| Category | Storage-specific addition | Why the network needs it | Source |
| --- | --- | --- | --- |
| Energy capacity | Energy storage capacity (MWh) and rated duration (hours at full power) | Distinguishes 1-h, 2-h, 4-h, long-duration assets — drives system-services value and ramp expectations | Grid Code (Storage Code User definitions) |
| Charge / discharge | Maximum charge rate (MW import) and maximum discharge rate (MW export); whether equal or asymmetric | Sets bidirectional connection capacity — billing & protection differ from a one-way generator | CUSC App. C |
| Connection capacity registration | Both **import** capacity and **export** capacity declared separately on the application | Network treats the asset as both a load and a generator — separate capacity products apply | CUSC §2.2.4 / §2.3 |
| State-of-charge management | Operating envelope (min / max state-of-charge), round-trip efficiency, degradation profile | Lets NESO model availability and balancing-market capability | NESO Storage EU Code Users guidance |
| Ancillary-service capability | Frequency response (dynamic / static), reactive power range, black-start capability declaration | Storage is the marginal source of system services — declaring capability matters commercially | CUSC App. F3 / F4 |
| Dynamic stability | Inverter control parameters, grid-forming vs grid-following declaration, fault-ride-through curves | System operator now actively values grid-forming storage | Grid Code CC.6.3 (FRT) |
| Co-location declaration | If storage shares a site with generation or demand, declared as such — see Mixed section below | Drives the technical compliance pathway (parallel vs consolidated connection) | NESO Co-location Guidance §2 |

Notes:

- NESO expects to award connection agreements to over 80 GW of battery energy storage by 2035 under the Gate 2 framework.

---

## 4. Mixed / Co-located

Sites that combine two or more technologies — typically solar + battery, wind + battery, or generation alongside on-site demand. NESO's **Guidance Notes for Co-location of Different Technologies (Issue 3.1, June 2025)** set the compliance pathway.

| Category | What the developer submits | Why the network needs it | Source |
| --- | --- | --- | --- |
| Configuration type | Declaration of **Parallel** (each technology has its own connection point) or **Consolidated** (technologies share a connection point) | Determines which compliance process applies, end to end | NESO Co-location §2.1 / §2.2 |
| Control architecture | For Consolidated sites: **Independently Controlled** (each tech has its own controller) or **Supplementary Controlled** (one master controller dispatches the site) | Compliance tests differ — Independently Controlled is treated unit-by-unit; Supplementary Controlled requires whole-site testing | NESO Co-location §2.2.1 / §2.2.2 |
| Per-technology capacity | Each technology declared separately: e.g. PV 100 MW, BESS 50 MW / 200 MWh, on-site demand 10 MVA | Each tech has its own Grid Code data set; the network needs to size protection and connection assets for each | CUSC §2.2.4 |
| Combined site limits | Firm export capacity (the agreed maximum the whole site can export at any moment) and total import capacity | The connection asset is sized for the combined limit, which is usually less than the sum of the parts | CUSC App. C |
| Site dispatch logic | Control philosophy showing how the technologies share the connection — priority rules, curtailment order, mode of storage operation | Drives what the system operator can rely on dispatch-wise; for Supplementary Controlled sites this is the basis of compliance | NESO Co-location §3 |
| Storage flow declaration | For storage co-located with generation: declared as import-only, export-only, or import + export | Affects strategic alignment under Gate 2 — export-only storage with generation does not count toward the BESS / LDES strategic category | Gate 2 Criteria Methodology |
| Sequenced commissioning plan | Order in which technologies will be commissioned and the milestones at which interim / final operational notifications are issued for each | Lets the system operator stage energisation safely | NESO Co-location §3.2 |
| Substantial modifications | Declaration of any future changes (e.g. adding storage to an existing PV site) — treated as a Substantial Modification with re-assessment | Triggers a partial re-application; NESO publishes worked examples | NESO Co-location Appendix B |

---

## Primary sources

- **CUSC** (Connection and Use of System Code) — current version, 1 April 2026.
- **The Grid Code** — current version, NESO.
- **Gate 2 Criteria Methodology (G2CM)** — NESO / Ofgem, December 2025.
- **Connections Network Design Methodology (CNDM)** — NESO, December 2025.
- **Demand Connections Reform — Call for Input** — Ofgem, 13 February 2026.
- **Guidance Notes for Co-location of Different Technologies, Issue 3.1** — NESO, June 2025.
- **TMO4+ Summary Decision Document** — Ofgem, April 2025.
