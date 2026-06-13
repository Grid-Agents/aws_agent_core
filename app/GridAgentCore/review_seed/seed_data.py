"""Synthetic grid interconnection submission bundles used as demo seed data.

Each project is a *bundle*: a filled application form plus the supporting
documents (land lease, financial statement, planning consent, single-line
diagram, type-test certificate, etc.) whose claims the form relies on. A few
sections deliberately contradict their own supporting document so the review
agent has genuine findings to surface (marked with a ``# DEFICIENCY`` comment).

Field schemas are drawn from
``interactive-pages/connection-application-data/{transmission,distribution}.md``.
The generator (``generate_seed.py``) renders every entry here to PDF; the
backend (``grid_agent_core/review_api.py``) parses those PDFs back into
sections at review time. This module is only consumed by the generator.
"""

from __future__ import annotations

# Each project:
#   id, name, applicant, level (transmission|distribution),
#   conn_type (generation|demand|storage|mixed), capacity, status, submitted (date)
#   sections: [{id, title, requirement, submitted, docs: [filenames]}]
#   documents: [{filename, title, subtitle, paras: [str]}]

PROJECTS: list[dict] = [
    # ------------------------------------------------------------------ TX GEN
    {
        "id": "TX-GEN-001",
        "name": "Thornholme Wind Farm",
        "applicant": "Thornholme Renewables Ltd",
        "level": "transmission",
        "conn_type": "generation",
        "capacity": "400 MW onshore wind",
        "status": "Under review",
        "submitted": "2026-04-18",
        "sections": [
            {
                "id": "site-location",
                "title": "Site & location",
                "requirement": "Site address plus GPS coordinates (WGS84, 3 d.p.). "
                "Source: Gate 2 Criteria Methodology §4.1b.",
                "submitted": "Thornholme Moor, near Driffield, East Riding of Yorkshire, "
                "YO25 3QF. Point of connection at 54.012 N, -0.471 E (WGS84). The site "
                "abuts the existing 400 kV Creyke Beck corridor approximately 6 km to the west.",
                "docs": ["red_line_boundary_plan.pdf"],
            },
            {
                "id": "land-control",
                "title": "Land — control",
                "requirement": "Evidence of land rights — freehold, lease, or option "
                "agreement of at least 20 years. Source: Gate 2 §4.1c.",
                # DEFICIENCY: the lease in the bundle runs only 15 years (< 20-year floor).
                "submitted": "The developer holds an executed option-to-lease over the "
                "entire red-line area. Land rights are secured for the operational life of "
                "the project, satisfying the Gate 2 land-control readiness criterion.",
                "docs": ["land_lease_agreement.pdf"],
            },
            {
                "id": "planning",
                "title": "Planning",
                "requirement": "Planning consent status — submitted, granted, or DCO "
                "(projects above 50 MW onshore use the DCO route). Source: Gate 2 §5.",
                "submitted": "The project exceeds 50 MW onshore and is consented under a "
                "Development Consent Order granted by the Secretary of State on 2025-11-03 "
                "(ref. EN010142). The DCO authorises up to 420 MW of installed capacity.",
                "docs": ["planning_consent.pdf"],
            },
            {
                "id": "project-capacity",
                "title": "Project capacity",
                "requirement": "Megawatt capacity per technology plus total connection "
                "capacity requested. Source: CUSC §2.2.4; Gate 2 §4.1b.",
                "submitted": "Total Transmission Entry Capacity (TEC) requested: 400 MW. "
                "Single technology (onshore wind), 80 x 5 MW turbines. No phased ramp; full "
                "capacity sought from the connection date.",
                "docs": [],
            },
            {
                "id": "company",
                "title": "Company",
                "requirement": "Corporate identity, ownership, and financial standing. "
                "Source: CUSC Schedule 2 Exhibit B; CUSC §2 Part III.",
                "submitted": "Thornholme Renewables Ltd (company no. 11234567) is a wholly "
                "owned subsidiary of Northbank Energy Capital. Audited net assets of "
                "£182m and committed equity of £140m are available for the project.",
                "docs": ["financial_statement.pdf"],
            },
            {
                "id": "plant-protection",
                "title": "Plant — protection",
                "requirement": "Protection relay settings and fault-clearance times that "
                "align with the network's own protection. Source: CUSC Appendix F4.",
                "submitted": "Main and backup distance protection with a fault-clearance "
                "time of 80 ms at the 400 kV point of connection, co-ordinated with NESO's "
                "Creyke Beck zone settings. Full F4 schedule attached.",
                "docs": ["protection_settings_f4.pdf"],
            },
            {
                "id": "network-studies",
                "title": "Network studies",
                "requirement": "Steady-state load flow, fault-level analysis, and transient "
                "stability assessment. Source: Grid Code Connection Conditions; CNDM Dec 2025.",
                "submitted": "Load-flow and fault-level studies completed against the 2030 "
                "NESO base case show no thermal or voltage violations. Transient stability "
                "confirmed for the three-phase fault-ride-through envelope.",
                "docs": [],
            },
        ],
        "documents": [
            {
                "filename": "land_lease_agreement.pdf",
                "title": "Option to Lease — Land at Thornholme Moor",
                "subtitle": "Between Thornholme Estates LLP (Landowner) and "
                "Thornholme Renewables Ltd (Developer)",
                "paras": [
                    "1. GRANT. The Landowner grants to the Developer an exclusive option "
                    "to take a lease of the Property edged red on the attached plan, for "
                    "the purpose of constructing and operating an onshore wind generating "
                    "station and associated infrastructure.",
                    "2. OPTION PERIOD. The option may be exercised at any time during the "
                    "period of five (5) years from the date of this Agreement.",
                    # DEFICIENCY: 15-year term, below the Gate 2 20-year land-control floor.
                    "3. LEASE TERM. Upon exercise, the term of the lease shall be fifteen "
                    "(15) years commencing on the date of exercise, with no contractual "
                    "right of renewal.",
                    "4. RENT. An annual rent of £950 per hectare, reviewed every five years "
                    "in line with the Retail Prices Index.",
                    "5. AREA. The demised area extends to 188 hectares as shown edged red "
                    "on Plan TH-RL-01.",
                ],
            },
            {
                "filename": "red_line_boundary_plan.pdf",
                "title": "Red-Line Boundary Plan TH-RL-01",
                "subtitle": "Site outline, Thornholme Moor — scale 1:5000",
                "paras": [
                    "Drawing reference: TH-RL-01, Revision C, dated 2026-03-30.",
                    "The red-line boundary encloses 188 hectares centred on grid reference "
                    "TA 045 612. Postcode YO25 3QF. The plan shows the turbine layout, "
                    "internal access tracks, the on-site 33/400 kV substation compound, and "
                    "the cable corridor to the Creyke Beck connection point.",
                    "Energy-density check: 188 ha for 400 MW equals 0.47 ha/MW, which "
                    "exceeds Ofgem's minimum acreage for onshore wind under the Gate 2 "
                    "energy-density table.",
                ],
            },
            {
                "filename": "planning_consent.pdf",
                "title": "Development Consent Order EN010142",
                "subtitle": "The Thornholme Wind Farm Order 2025",
                "paras": [
                    "The Secretary of State for Energy Security and Net Zero, having "
                    "considered the application and the Examining Authority's report, makes "
                    "the following Order under the Planning Act 2008.",
                    "Article 2 — Development consent is granted for an onshore wind "
                    "generating station with an installed capacity of up to 420 MW, "
                    "comprising up to 80 turbines, on-site substation, and grid connection "
                    "works at Thornholme Moor.",
                    "Date of decision: 3 November 2025. This Order comes into force on "
                    "24 November 2025.",
                ],
            },
            {
                "filename": "financial_statement.pdf",
                "title": "Statement of Financial Position",
                "subtitle": "Thornholme Renewables Ltd — year ended 31 December 2025",
                "paras": [
                    "Audited accounts (abridged). Total assets £214m; total liabilities "
                    "£32m; net assets £182m.",
                    "Parent company guarantee: Northbank Energy Capital has confirmed "
                    "committed equity funding of £140m, with a further £260m of senior debt "
                    "underwritten by a syndicate led by NatWest, subject to financial close.",
                    "Auditor's opinion: unqualified.",
                ],
            },
            {
                "filename": "protection_settings_f4.pdf",
                "title": "CUSC Appendix F4 — Protection Settings Schedule",
                "subtitle": "Thornholme 400 kV connection",
                "paras": [
                    "Main protection: dual-redundant distance protection (Zone 1 reach 80% "
                    "of line, instantaneous; Zone 2 120%, 350 ms).",
                    "Backup protection: directional earth-fault and overcurrent.",
                    "Total fault-clearance time at the point of connection: 80 ms for a "
                    "three-phase fault, within the NESO Creyke Beck zone requirement of "
                    "100 ms. Breaker-fail protection set at 150 ms.",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------ TX DEM
    {
        "id": "TX-DEM-002",
        "name": "Aldgate Hyperscale Data Centre",
        "applicant": "Aldgate Digital Infrastructure plc",
        "level": "transmission",
        "conn_type": "demand",
        "capacity": "300 MW import",
        "status": "Under review",
        "submitted": "2026-05-02",
        "sections": [
            {
                "id": "project-site",
                "title": "Project & site",
                "requirement": "Site address plus coordinates and site classification "
                "(data centre, industrial, etc.). Source: CUSC application schedule.",
                "submitted": "Proposed hyperscale data-centre campus at Aldgate Park, "
                "Thurrock, RM18 8RH (51.478 N, 0.345 E). Classification: data centre, "
                "AI / cloud compute, served by the 400 kV Tilbury substation.",
                "docs": [],
            },
            {
                "id": "land-control",
                "title": "Land — control",
                "requirement": "Exclusive land access (proposed Gate-2-style readiness "
                "criterion). Source: Demand Connections CFI Feb 2026 §5.2.",
                "submitted": "Aldgate holds a 35-year registered leasehold over the entire "
                "12-hectare campus, granting exclusive possession from completion.",
                "docs": ["land_lease_agreement.pdf"],
            },
            {
                "id": "planning",
                "title": "Planning",
                "requirement": "Outline or full planning consent, or evidence of "
                "submission — strengthened readiness criterion for data centres. "
                "Source: CFI Feb 2026 §5.27.",
                # DEFICIENCY: only a screening request submitted, no consent — claim overstates readiness.
                "submitted": "Full planning permission for the data-centre campus has been "
                "secured from Thurrock Council, demonstrating the site is build-ready.",
                "docs": ["planning_status_letter.pdf"],
            },
            {
                "id": "commercial",
                "title": "Commercial",
                "requirement": "Commercial off-taker — for data centres, evidence of a "
                "customer / hyperscaler tenancy contract. Source: CFI Feb 2026 §5.2.",
                # DEFICIENCY: only non-binding heads of terms, not an executed tenancy contract.
                "submitted": "A hyperscale cloud provider has committed to anchor tenancy "
                "for 70% of the IT load under a signed contract, evidencing firm economic "
                "backing for the connection.",
                "docs": ["anchor_tenant_heads_of_terms.pdf"],
            },
            {
                "id": "project-capacity",
                "title": "Project capacity",
                "requirement": "Maximum demand (MW), minimum demand, import profile; for "
                "data centres the IT load curve and PUE. Source: Grid Code Demand Code (DC).",
                "submitted": "Maximum demand 300 MW; minimum (overnight) 180 MW. Near-flat "
                "24-hour import profile typical of AI training workloads. Design PUE 1.18 "
                "with evaporative-assisted cooling.",
                "docs": [],
            },
            {
                "id": "non-firm",
                "title": "Non-firm option",
                "requirement": "Willingness to accept a non-firm or interruptible "
                "connection. Source: CFI Feb 2026 §5.2 (Connect).",
                "submitted": "Aldgate will accept a non-firm connection for up to 60 MW of "
                "the total load, interruptible at 30 minutes' notice, in exchange for an "
                "earlier connection date.",
                "docs": [],
            },
            {
                "id": "securities",
                "title": "Securities",
                "requirement": "User commitment fee / financial security under CUSC "
                "Section 15. Source: CUSC §15 User Commitment Methodology.",
                "submitted": "Aldgate accepts the CUSC Section 15 user-commitment liability "
                "and will post a £24m on-demand bank guarantee at the offer-acceptance "
                "milestone.",
                "docs": ["financial_statement.pdf"],
            },
        ],
        "documents": [
            {
                "filename": "land_lease_agreement.pdf",
                "title": "Registered Lease — Aldgate Park, Thurrock",
                "subtitle": "Title number EX998877",
                "paras": [
                    "Term: 35 years from 1 January 2026, granting exclusive possession of "
                    "the land registered under title EX998877 (12.1 hectares).",
                    "Permitted use: data centre and ancillary plant including on-site "
                    "electrical infrastructure and standby generation.",
                    "The lease is registered at HM Land Registry and contains no break "
                    "clause exercisable by the landlord before year 25.",
                ],
            },
            {
                "filename": "planning_status_letter.pdf",
                "title": "Planning Status — Thurrock Council",
                "subtitle": "Re: Aldgate Park data-centre campus",
                "paras": [
                    "This letter confirms the current planning status of the proposed "
                    "development at Aldgate Park.",
                    # DEFICIENCY: only an EIA screening request submitted; no application, no consent.
                    "An EIA screening request was submitted to the Local Planning Authority "
                    "on 14 April 2026. A formal planning application has not yet been "
                    "submitted, and no planning permission has been granted to date.",
                    "The Council anticipates a screening opinion within the statutory "
                    "period. The applicant should not rely on this letter as evidence of "
                    "consent.",
                ],
            },
            {
                "filename": "anchor_tenant_heads_of_terms.pdf",
                "title": "Heads of Terms — Anchor Tenancy (Non-Binding)",
                "subtitle": "Aldgate Digital Infrastructure plc and [Cloud Provider]",
                "paras": [
                    "These Heads of Terms record the parties' current intentions in "
                    "relation to a prospective anchor tenancy and are expressly "
                    "SUBJECT TO CONTRACT and NON-BINDING.",
                    "Indicative commitment: up to 70% of available IT capacity, subject to "
                    "the negotiation and execution of a definitive lease and service "
                    "agreement, and to the tenant's internal investment approval.",
                    "Either party may withdraw at any time before execution of the "
                    "definitive agreements without liability.",
                ],
            },
            {
                "filename": "financial_statement.pdf",
                "title": "Statement of Financial Position",
                "subtitle": "Aldgate Digital Infrastructure plc — year ended 31 December 2025",
                "paras": [
                    "Total assets £640m; net assets £410m. Cash and committed facilities "
                    "of £150m are available for the first development phase.",
                    "A £24m on-demand guarantee facility has been confirmed by HSBC for the "
                    "purpose of CUSC Section 15 user commitment.",
                    "Auditor's opinion: unqualified.",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------ TX STO
    {
        "id": "TX-STO-003",
        "name": "Pennine Battery Storage",
        "applicant": "Pennine Flexible Power Ltd",
        "level": "transmission",
        "conn_type": "storage",
        "capacity": "200 MW / 800 MWh BESS",
        "status": "Under review",
        "submitted": "2026-04-29",
        "sections": [
            {
                "id": "energy-capacity",
                "title": "Energy capacity",
                "requirement": "Energy storage capacity (MWh) and rated duration. "
                "Source: Grid Code Storage Code user definitions.",
                "submitted": "Energy capacity 800 MWh at beginning of life, rated duration "
                "4 hours at 200 MW full discharge. Lithium-ion LFP chemistry.",
                "docs": [],
            },
            {
                "id": "charge-discharge",
                "title": "Charge / discharge",
                "requirement": "Maximum charge rate (MW import) and discharge rate (MW "
                "export); whether equal or asymmetric. Source: CUSC App. C.",
                "submitted": "Maximum discharge (export) 200 MW; maximum charge (import) "
                "200 MW. Symmetric bidirectional inverter rating.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "capacity-registration",
                "title": "Connection capacity registration",
                "requirement": "Both import capacity and export capacity declared "
                "separately. Source: CUSC §2.2.4 / §2.3.",
                # DEFICIENCY: declares 200 MW import but only 150 MW TEC export — mismatch with symmetric claim.
                "submitted": "Export (TEC) registered at 150 MW. Import capacity registered "
                "at 200 MW.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "land-control",
                "title": "Land — control",
                "requirement": "Evidence of land rights of at least 20 years. "
                "Source: Gate 2 §4.1c.",
                "submitted": "25-year lease executed over the 4-hectare site adjacent to "
                "the existing 275 kV Stalybridge substation.",
                "docs": ["land_lease_agreement.pdf"],
            },
            {
                "id": "ancillary-services",
                "title": "Ancillary-service capability",
                "requirement": "Frequency response (dynamic/static), reactive power range, "
                "black-start capability declaration. Source: CUSC App. F3 / F4.",
                # DEFICIENCY: black-start declared, but no capability statement is provided.
                "submitted": "Dynamic Containment and Dynamic Regulation capable across the "
                "full 200 MW. Reactive range +/- 0.95 power factor at the connection point. "
                "Black-start capable.",
                "docs": [],
            },
            {
                "id": "dynamic-stability",
                "title": "Dynamic stability",
                "requirement": "Inverter control parameters, grid-forming vs grid-following "
                "declaration, fault-ride-through curves. Source: Grid Code CC.6.3 (FRT).",
                "submitted": "Grid-forming inverters with virtual synchronous machine "
                "control. FRT compliant to the Grid Code CC.6.3.15 voltage-against-time "
                "profile, including the 140 ms zero-voltage ride-through requirement.",
                "docs": [],
            },
        ],
        "documents": [
            {
                "filename": "single_line_diagram.pdf",
                "title": "Single-Line Diagram — Pennine BESS",
                "subtitle": "200 MW / 800 MWh connection to 275 kV Stalybridge",
                "paras": [
                    "The site connects to the 275 kV busbar at Stalybridge via a 200 MVA "
                    "275/33 kV grid transformer and a 33 kV switchboard.",
                    "Power conversion: 40 x 5 MW grid-forming inverters arranged in "
                    "8 blocks, each block with its own 33/0.69 kV transformer.",
                    # Note: SLD transformer rated 200 MVA but TEC export limited to 150 MW per capacity reg.
                    "Metering point at the 275 kV connection. Export limited at the site "
                    "controller to the registered Transmission Entry Capacity.",
                ],
            },
            {
                "filename": "land_lease_agreement.pdf",
                "title": "Lease — Land adjacent to Stalybridge 275 kV",
                "subtitle": "Pennine Flexible Power Ltd",
                "paras": [
                    "Term: 25 years from completion, with a tenant-only option to renew "
                    "for a further 10 years.",
                    "Demised area: 4.0 hectares as shown on Plan PN-RL-02.",
                    "Permitted use: battery energy storage system and associated "
                    "electrical connection works.",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------ DX GEN
    {
        "id": "DX-GEN-004",
        "name": "Greenholt Solar Park",
        "applicant": "Greenholt Solar Ltd",
        "level": "distribution",
        "conn_type": "generation",
        "capacity": "24 MW solar PV (G99 Type C)",
        "status": "Under review",
        "submitted": "2026-05-08",
        "sections": [
            {
                "id": "applicant",
                "title": "Applicant",
                "requirement": "Customer name, address, agent / installer details. "
                "Source: G99 Design Phase.",
                "submitted": "Greenholt Solar Ltd, Unit 4 Maltings Business Park, "
                "Shrewsbury, SY1 4QD. Installer: Severn EPC Ltd (NICEIC approved). "
                "Agent contact: J. Marsh, grid connections.",
                "docs": [],
            },
            {
                "id": "project-type",
                "title": "Project type",
                "requirement": "G99 classification — Type A (<=1 MW), B (1-10 MW), "
                "C (10-50 MW), D (>=50 MW or TX-connected). Source: G99 §2.2.",
                "submitted": "24 MW registered capacity at 33 kV, classified as G99 "
                "Type C (10-50 MW). Connection to the WPD/National Grid Electricity "
                "Distribution 33 kV network at Greenholt primary.",
                "docs": [],
            },
            {
                "id": "connection-point",
                "title": "Connection point",
                "requirement": "Proposed metering location plus maximum capacity (kVA) at "
                "each point. Source: G99 Design Phase.",
                "submitted": "Single point of connection at Greenholt 33 kV primary "
                "substation. Maximum export capacity 24 MVA; import (auxiliaries) 0.5 MVA.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "pgmd",
                "title": "PGMD (Type B/C/D)",
                "requirement": "Power Generating Module Document — compliance statement plus "
                "full technical data sheet evidencing every G99 criterion. "
                "Source: G99 Construction Phase.",
                # DEFICIENCY: section claims PGMD attached, but no PGMD is in the bundle.
                "submitted": "A complete Power Generating Module Document is enclosed, "
                "confirming compliance with all relevant G99 criteria for the inverter "
                "fleet and the site as a whole.",
                "docs": [],  # intentionally no PGMD document supplied
            },
            {
                "id": "protection-islanding",
                "title": "Protection & islanding",
                "requirement": "Relay settings and the anti-islanding scheme — critical for "
                "safety of DNO field staff. Source: G99 §16-19.",
                # DEFICIENCY: loss-of-mains settings omitted from the attached schedule.
                "submitted": "Interface protection at the 33 kV point of connection with "
                "under/over voltage and under/over frequency elements per G99 Table 10.1. "
                "Settings schedule attached.",
                "docs": ["protection_settings.pdf"],
            },
            {
                "id": "type-test",
                "title": "Type-test evidence",
                "requirement": "Manufacturer certification that the unit passes the relevant "
                "G99 type test. Source: G99 Construction Phase; DCode DPC §7.",
                "submitted": "Inverter type-test certificates to G99 Issue 1 are enclosed "
                "for the Sungrow SG3600UD-MV power units.",
                "docs": ["type_test_certificate.pdf"],
            },
        ],
        "documents": [
            {
                "filename": "single_line_diagram.pdf",
                "title": "Single-Line Diagram — Greenholt Solar Park",
                "subtitle": "24 MW PV connection to Greenholt 33 kV primary",
                "paras": [
                    "PV array of 6 x 4 MW blocks, each with a 4 MVA 0.69/33 kV transformer, "
                    "combined onto a 33 kV switchboard.",
                    "Single point of connection to the DNO 33 kV busbar at Greenholt "
                    "primary, via a metered circuit breaker with interface protection.",
                    "Maximum export 24 MVA; site auxiliary import 0.5 MVA.",
                ],
            },
            {
                "filename": "protection_settings.pdf",
                "title": "Interface Protection Settings Schedule",
                "subtitle": "Greenholt Solar Park — 33 kV point of connection",
                "paras": [
                    "Voltage protection: U< stage 1 -13% 2.5 s; U< stage 2 -20% 0.5 s; "
                    "U> stage 1 +10% 1.0 s; U> stage 2 +13% 0.5 s.",
                    "Frequency protection: f< 47.5 Hz 20 s; f< 47.0 Hz 0.5 s; "
                    "f> 51.5 Hz 90 s; f> 52.0 Hz 0.5 s.",
                    # DEFICIENCY: no loss-of-mains / RoCoF or vector-shift anti-islanding element listed.
                    "Note: the loss-of-mains (RoCoF) element and its stability setting are "
                    "to be confirmed at the commissioning stage and are not included in "
                    "this schedule.",
                ],
            },
            {
                "filename": "type_test_certificate.pdf",
                "title": "Type Test Certificate — Sungrow SG3600UD-MV",
                "subtitle": "Engineering Recommendation G99 compliance",
                "paras": [
                    "This certifies that the Sungrow SG3600UD-MV power unit has been tested "
                    "in accordance with the type-test requirements of ENA Engineering "
                    "Recommendation G99 Issue 1.",
                    "Verified capabilities: reactive power capability, voltage ride-through, "
                    "frequency response, and protection function operation.",
                    "Certificate issued by an accredited test laboratory; reference "
                    "SGR-G99-2024-0417.",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------ DX STO
    {
        "id": "DX-STO-005",
        "name": "Riverside Battery Storage",
        "applicant": "Riverside Flex Ltd",
        "level": "distribution",
        "conn_type": "storage",
        "capacity": "8 MW / 16 MWh BESS (G99 Type B)",
        "status": "Under review",
        "submitted": "2026-05-11",
        "sections": [
            {
                "id": "project-type",
                "title": "Project type",
                "requirement": "G99 classification and pathway. Source: G99 §2.2.",
                "submitted": "8 MW / 16 MWh battery energy storage system at 11 kV, "
                "classified as G99 Type B (1-10 MW).",
                "docs": [],
            },
            {
                "id": "energy-capacity",
                "title": "Energy capacity",
                "requirement": "Energy storage capacity (MWh) and rated duration. "
                "Source: G99 (PGM with Electricity Storage).",
                "submitted": "16 MWh usable energy capacity, rated duration 2 hours at "
                "8 MW. LFP chemistry with augmentation planned at year 7.",
                "docs": [],
            },
            {
                "id": "import-export",
                "title": "Import + export capacity",
                "requirement": "Both import and export capacity declared. Source: DCUSA.",
                "submitted": "Export capacity 8 MW; import (charge) capacity 8 MW. Charging "
                "from the grid permitted for arbitrage and balancing services.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "threshold-check",
                "title": "Threshold check",
                "requirement": "Confirmation that export per phase exceeds 3.68 kW (the G99 "
                "trigger). Source: G99 / G98 split.",
                "submitted": "Export far exceeds the 3.68 kW per phase G98/G99 threshold; "
                "G99 application pathway confirmed.",
                "docs": [],
            },
            {
                "id": "grid-forming",
                "title": "Grid-forming declaration",
                "requirement": "Whether the inverter is grid-following (default) or "
                "grid-forming. Source: G99 Issue 2.",
                # DEFICIENCY: declares grid-forming, but the attached type-test cert is grid-following.
                "submitted": "The inverters are grid-forming, providing virtual inertia and "
                "fault-level support to the local 11 kV network.",
                "docs": ["type_test_certificate.pdf"],
            },
            {
                "id": "anti-islanding",
                "title": "Anti-islanding (storage-specific)",
                "requirement": "Anti-islanding settings appropriate to a bidirectional "
                "asset. Source: G99 §16-19 (Issue 2 storage clauses).",
                "submitted": "Loss-of-mains protection by RoCoF set at 1.0 Hz/s with a "
                "0.5 s confirmation time, co-ordinated with the DNO 11 kV scheme. No "
                "on-site generation to co-ordinate with.",
                "docs": ["protection_settings.pdf"],
            },
        ],
        "documents": [
            {
                "filename": "single_line_diagram.pdf",
                "title": "Single-Line Diagram — Riverside BESS",
                "subtitle": "8 MW / 16 MWh connection to 11 kV",
                "paras": [
                    "Four 2 MW inverter-transformer skids combined onto an 11 kV "
                    "switchboard, connected to the DNO 11 kV network via a metered ring "
                    "main unit.",
                    "A grid-charging path is provided: the BESS can import from the 11 kV "
                    "network as well as export.",
                    "Site auxiliary supply taken from the LV board of skid 1.",
                ],
            },
            {
                "filename": "type_test_certificate.pdf",
                "title": "Type Test Certificate — Power Electronics FS3450",
                "subtitle": "Engineering Recommendation G99 Issue 2",
                "paras": [
                    "This certifies that the inverter has been type-tested in accordance "
                    "with ENA Engineering Recommendation G99 Issue 2.",
                    # DEFICIENCY: certificate states grid-following control mode.
                    "Control mode: grid-following (current-source) operation. The unit was "
                    "not tested for grid-forming (voltage-source) operation, and no virtual "
                    "inertia capability is certified under this report.",
                    "Verified: LVRT, reactive capability, and frequency response in "
                    "grid-following mode. Reference PE-G99v2-2025-1180.",
                ],
            },
            {
                "filename": "protection_settings.pdf",
                "title": "Interface Protection Settings — Riverside BESS",
                "subtitle": "11 kV point of connection",
                "paras": [
                    "Loss of mains: RoCoF 1.0 Hz/s, 0.5 s confirmation time.",
                    "Voltage: U< -13% 2.5 s, U< -20% 0.5 s, U> +10% 1.0 s, U> +13% 0.5 s.",
                    "Frequency: f< 47.5 Hz 20 s, f< 47.0 Hz 0.5 s, f> 51.5 Hz 90 s.",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------ DX MIX
    {
        "id": "DX-MIX-006",
        "name": "Meadowbank Solar + Storage",
        "applicant": "Meadowbank Energy Ltd",
        "level": "distribution",
        "conn_type": "mixed",
        "capacity": "15 MW PV + 10 MW / 20 MWh BESS",
        "status": "Under review",
        "submitted": "2026-05-09",
        "sections": [
            {
                "id": "per-technology",
                "title": "Per-technology applications",
                "requirement": "One G99 application per generator / storage unit, each with "
                "its own Type and form set. Source: G99 §2.2; DCode DPC §6.",
                "submitted": "Two G99 modules: PV array 15 MW (Type C) and BESS 10 MW / "
                "20 MWh (Type C). Each declared with its own technical data set and "
                "registered capacity.",
                "docs": [],
            },
            {
                "id": "combined-capacities",
                "title": "Combined site capacities",
                "requirement": "Firm export capacity and total import capacity for the whole "
                "site. Source: DCUSA capacity registration.",
                "submitted": "Firm export capacity 15 MW (site controller caps combined "
                "export). Total import capacity 10 MW for BESS charging plus 0.3 MW "
                "auxiliaries.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "storage-flow",
                "title": "Storage flow declaration",
                "requirement": "BESS declared as import-only, export-only, or import + "
                "export, and whether it can charge from the grid or only from co-located "
                "generation. Source: G99; DCUSA.",
                # DEFICIENCY: declares export-only / PV-charged only, but SLD shows a grid-charging path.
                "submitted": "The BESS is configured export-only and charges exclusively "
                "from the co-located PV array. It qualifies for a single export-only "
                "commercial registration and cannot import from the grid.",
                "docs": ["single_line_diagram.pdf"],
            },
            {
                "id": "site-dispatch",
                "title": "Site dispatch logic",
                "requirement": "How the technologies share the connection — priority rules, "
                "curtailment order, BESS charge/discharge logic. Source: NESO Co-location "
                "Guidance (technical principles).",
                "submitted": "Master site controller prioritises direct PV export to the "
                "firm limit; surplus PV charges the BESS; the BESS discharges in the "
                "evening peak. Combined export is hard-limited to 15 MW.",
                "docs": ["control_philosophy.pdf"],
            },
            {
                "id": "flexible-connection",
                "title": "Curtailment / flexible-connection terms",
                "requirement": "Acceptance of an active network management (ANM) contract — "
                "curtailment in exchange for an earlier connection. Source: DCode DPC §6 "
                "(flexible).",
                "submitted": "Meadowbank accepts an ANM-managed flexible connection and "
                "will install the DNO's ANM interface for real-time export curtailment.",
                "docs": [],
            },
        ],
        "documents": [
            {
                "filename": "single_line_diagram.pdf",
                "title": "Single-Line Diagram — Meadowbank Solar + Storage",
                "subtitle": "15 MW PV + 10 MW BESS shared 33 kV connection",
                "paras": [
                    "PV array (15 MW) and BESS (10 MW / 20 MWh) are combined onto a common "
                    "33 kV switchboard sharing a single metered point of connection.",
                    # DEFICIENCY: BESS sits on the shared AC bus with a closed grid-import path.
                    "The BESS inverters are connected to the shared 33 kV AC bus through a "
                    "bidirectional breaker. With the PV array offline, the BESS can charge "
                    "from the grid through this path; there is no DC-coupling that would "
                    "restrict charging to PV only.",
                    "A site controller enforces the combined 15 MW export limit.",
                ],
            },
            {
                "filename": "control_philosophy.pdf",
                "title": "Site Control Philosophy — Meadowbank",
                "subtitle": "Dispatch and curtailment logic",
                "paras": [
                    "Priority 1: export available PV up to the 15 MW firm limit.",
                    "Priority 2: charge the BESS from surplus PV above the firm limit.",
                    "Priority 3: discharge the BESS into the evening peak within the firm "
                    "limit. The controller responds to DNO ANM curtailment signals within "
                    "two seconds.",
                ],
            },
        ],
    },
]
