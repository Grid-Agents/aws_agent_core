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

Document model (consumed by ``generate_seed.render_support_doc``):
    {
      "filename": str, "title": str, "subtitle": str,
      "ref": {label: value, ...},                 # reference / parties table
      "sections": [{"heading": str, "paras": [str, ...]}, ...],
      "schedule": {"title", "columns": [...], "rows": [[...], ...]},  # optional
      "execution": [str, ...],                     # optional signature lines
    }
The deliberately rich, multi-section documents make the review non-trivial:
the planted defect is buried in otherwise-plausible boilerplate, so the agent
has to actually read the evidence rather than skim three sentences.
"""

from __future__ import annotations

# Each project:
#   id, name, applicant, level (transmission|distribution),
#   conn_type (generation|demand|storage|mixed), capacity, status, submitted (date)
#   sections: [{id, title, requirement, submitted, docs: [filenames]}]
#   documents: [<document model above>]

PROJECTS: list[dict] = [
    # ================================================================== TX GEN
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
                "title": "Agreement for Option to Lease",
                "subtitle": "Land at Thornholme Moor, East Riding of Yorkshire",
                "ref": {
                    "Landlord": "Thornholme Estates LLP (registered OC418822)",
                    "Tenant": "Thornholme Renewables Ltd (company no. 11234567)",
                    "Property": "188 ha edged red on Plan TH-RL-01 at Thornholme Moor, YO25 3QF",
                    "Title number": "YEA 552310 (freehold, registered)",
                    "Dated": "9 February 2026",
                },
                "sections": [
                    {
                        "heading": "1. Definitions and interpretation",
                        "paras": [
                            "1.1 In this Agreement: \"Option\" means the option to take a lease "
                            "of the Property granted under clause 2; \"Option Period\" has the "
                            "meaning given in clause 3; \"Lease\" means the lease to be granted "
                            "in the form of the draft annexed at Schedule 1; and \"Generating "
                            "Station\" means an onshore wind electricity generating station and "
                            "all associated infrastructure.",
                            "1.2 Clause headings do not affect interpretation. References to a "
                            "party include that party's successors and permitted assigns. Where "
                            "the context admits, the singular includes the plural.",
                        ],
                    },
                    {
                        "heading": "2. Grant of option",
                        "paras": [
                            "2.1 In consideration of the Option Fee, the Landlord grants to the "
                            "Tenant an exclusive option to call for the grant of the Lease of "
                            "the Property for the purpose of constructing, commissioning and "
                            "operating the Generating Station and associated grid connection "
                            "works.",
                            "2.2 The Option is personal to the Tenant but may be assigned to a "
                            "member of the Tenant's group or to a funder by way of security "
                            "without the Landlord's consent.",
                        ],
                    },
                    {
                        "heading": "3. Option period",
                        "paras": [
                            "3.1 The Option may be exercised by the Tenant serving an Option "
                            "Notice on the Landlord at any time during the period of five (5) "
                            "years from the date of this Agreement (the \"Option Period\").",
                            "3.2 If the Option is not exercised before the end of the Option "
                            "Period it shall lapse and the parties shall be released from "
                            "further obligation, save for accrued liabilities.",
                        ],
                    },
                    {
                        "heading": "4. Term of the lease",
                        "paras": [
                            # DEFICIENCY: 15-year term, below the Gate 2 20-year land-control floor.
                            "4.1 Upon exercise of the Option, the Lease shall be granted for a "
                            "term of fifteen (15) years commencing on the date of exercise. The "
                            "Lease contains no contractual right of renewal and is excluded from "
                            "the security-of-tenure provisions of sections 24 to 28 of the "
                            "Landlord and Tenant Act 1954.",
                            "4.2 The Tenant shall yield up the Property at the end of the term in "
                            "accordance with the decommissioning obligations in clause 9.",
                        ],
                    },
                    {
                        "heading": "5. Rent and review",
                        "paras": [
                            "5.1 The annual rent reserved by the Lease shall be £950 per hectare "
                            "of the Property, payable quarterly in advance.",
                            "5.2 The rent shall be reviewed on each fifth anniversary of the term "
                            "commencement date in line with the Retail Prices Index, upward only.",
                        ],
                    },
                    {
                        "heading": "6. Demised area and plan",
                        "paras": [
                            "6.1 The Property comprises 188 hectares of agricultural land shown "
                            "edged red on Plan TH-RL-01 (Revision C). The Tenant is granted "
                            "rights of access over the coloured-brown accessways for "
                            "construction and operational traffic.",
                        ],
                    },
                    {
                        "heading": "7. Tenant covenants",
                        "paras": [
                            "7.1 The Tenant covenants to use the Property only for the permitted "
                            "use; to keep the Generating Station insured to full reinstatement "
                            "value; to comply with all statutory consents; and to indemnify the "
                            "Landlord against third-party claims arising from the Tenant's works.",
                        ],
                    },
                    {
                        "heading": "8. Landlord covenants",
                        "paras": [
                            "8.1 The Landlord covenants for quiet enjoyment and not to grant "
                            "competing rights over the Property during the Option Period that "
                            "would frustrate the development of the Generating Station.",
                        ],
                    },
                    {
                        "heading": "9. Decommissioning and reinstatement",
                        "paras": [
                            "9.1 On expiry the Tenant shall remove all above-ground plant and "
                            "reinstate the Property to agricultural use, and shall maintain a "
                            "decommissioning bond from year ten of the term.",
                        ],
                    },
                    {
                        "heading": "10. Governing law",
                        "paras": [
                            "10.1 This Agreement and the Lease are governed by the law of "
                            "England and Wales and the parties submit to the exclusive "
                            "jurisdiction of the courts of England and Wales.",
                        ],
                    },
                ],
                "execution": [
                    "Signed for and on behalf of Thornholme Estates LLP ........................  Date ............",
                    "Signed for and on behalf of Thornholme Renewables Ltd ...................  Date ............",
                    "In the presence of (witness) ......................................................................",
                ],
            },
            {
                "filename": "red_line_boundary_plan.pdf",
                "title": "Red-Line Boundary Plan TH-RL-01",
                "subtitle": "Site outline, Thornholme Moor — scale 1:5000, Revision C",
                "ref": {
                    "Drawing reference": "TH-RL-01, Revision C",
                    "Date": "30 March 2026",
                    "Grid reference": "TA 045 612",
                    "Postcode": "YO25 3QF",
                    "Datum": "WGS84 / OSGB36",
                },
                "sections": [
                    {
                        "heading": "1. Drawing description",
                        "paras": [
                            "The red-line boundary encloses 188 hectares centred on grid "
                            "reference TA 045 612. The plan shows the turbine layout (80 "
                            "positions), internal access tracks, the on-site 33/400 kV "
                            "substation compound, the temporary construction compound and "
                            "laydown areas, and the underground cable corridor to the Creyke "
                            "Beck connection point approximately 6 km to the west.",
                        ],
                    },
                    {
                        "heading": "2. Connection point coordinates",
                        "paras": [
                            "The proposed point of connection lies on the 400 kV Creyke Beck "
                            "corridor at the coordinates listed in the schedule below.",
                        ],
                    },
                    {
                        "heading": "3. Energy-density check",
                        "paras": [
                            "188 ha for 400 MW equals 0.47 ha/MW, which exceeds Ofgem's minimum "
                            "acreage for onshore wind under the Gate 2 energy-density table. The "
                            "layout maintains the statutory toppling distance from the red-line "
                            "boundary at every turbine position.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Schedule A — Key coordinates (WGS84)",
                    "columns": ["Feature", "Latitude (N)", "Longitude (E)", "Note"],
                    "rows": [
                        ["Point of connection", "54.012", "-0.471", "400 kV corridor"],
                        ["Substation compound", "54.018", "-0.452", "33/400 kV"],
                        ["Site centroid", "54.021", "-0.438", "TA 045 612"],
                        ["Northern boundary", "54.034", "-0.441", "red line"],
                        ["Southern boundary", "54.008", "-0.435", "red line"],
                    ],
                },
            },
            {
                "filename": "planning_consent.pdf",
                "title": "Development Consent Order EN010142",
                "subtitle": "The Thornholme Wind Farm Order 2025",
                "ref": {
                    "Order reference": "EN010142",
                    "Applicant": "Thornholme Renewables Ltd",
                    "Decision": "Granted",
                    "Date of decision": "3 November 2025",
                    "In force from": "24 November 2025",
                },
                "sections": [
                    {
                        "heading": "Preamble",
                        "paras": [
                            "The Secretary of State for Energy Security and Net Zero, having "
                            "considered the application and the Examining Authority's report "
                            "dated 5 August 2025, and being satisfied that the development is a "
                            "Nationally Significant Infrastructure Project under the Planning Act "
                            "2008, makes the following Order.",
                        ],
                    },
                    {
                        "heading": "Article 2 — Grant of development consent",
                        "paras": [
                            "Development consent is granted for an onshore wind generating "
                            "station with an installed capacity of up to 420 MW, comprising up "
                            "to 80 turbines with a maximum blade-tip height of 200 m, an on-site "
                            "substation, underground cabling, and grid connection works at "
                            "Thornholme Moor, in accordance with the works plans certified under "
                            "Article 30.",
                        ],
                    },
                    {
                        "heading": "Article 3 — Limits of deviation",
                        "paras": [
                            "In carrying out the authorised development the undertaker may "
                            "deviate laterally within the limits shown on the works plans and "
                            "vertically to the heights specified in the design parameters at "
                            "Schedule 2.",
                        ],
                    },
                    {
                        "heading": "Requirements (Schedule 1)",
                        "paras": [
                            "No part of the authorised development may commence until details of "
                            "surface-water drainage, construction traffic management, and a "
                            "biodiversity net-gain plan have been submitted to and approved by "
                            "the relevant planning authority. Commissioning is subject to a "
                            "noise-management scheme.",
                        ],
                    },
                ],
                "execution": [
                    "Signed by authority of the Secretary of State ......................................",
                    "A Senior Civil Servant, Department for Energy Security and Net Zero",
                ],
            },
            {
                "filename": "financial_statement.pdf",
                "title": "Statement of Financial Position",
                "subtitle": "Thornholme Renewables Ltd — year ended 31 December 2025",
                "ref": {
                    "Company": "Thornholme Renewables Ltd",
                    "Company number": "11234567",
                    "Parent": "Northbank Energy Capital",
                    "Auditor": "Greaves & Hall LLP",
                    "Basis": "Audited, abridged",
                },
                "sections": [
                    {
                        "heading": "1. Basis of preparation",
                        "paras": [
                            "The financial statements have been prepared in accordance with "
                            "FRS 102 and the Companies Act 2006. The company is a special-purpose "
                            "vehicle whose principal activity is the development of the "
                            "Thornholme onshore wind generating station.",
                        ],
                    },
                    {
                        "heading": "2. Funding and parent support",
                        "paras": [
                            "Northbank Energy Capital has confirmed committed equity funding of "
                            "£140m by way of an equity-commitment letter dated 12 January 2026. "
                            "A further £260m of senior debt has been underwritten by a syndicate "
                            "led by NatWest, subject to financial close and customary conditions "
                            "precedent.",
                            "A parent company guarantee in favour of the network operator is "
                            "available to support the CUSC securities obligation.",
                        ],
                    },
                    {
                        "heading": "3. Auditor's opinion",
                        "paras": [
                            "In our opinion the financial statements give a true and fair view "
                            "of the state of the company's affairs as at 31 December 2025. The "
                            "opinion is unqualified.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Statement of financial position (£m)",
                    "columns": ["Item", "2025", "2024"],
                    "rows": [
                        ["Non-current assets", "196", "121"],
                        ["Current assets", "18", "12"],
                        ["Total assets", "214", "133"],
                        ["Current liabilities", "(9)", "(6)"],
                        ["Non-current liabilities", "(23)", "(15)"],
                        ["Net assets", "182", "112"],
                        ["Committed equity (parent)", "140", "90"],
                    ],
                },
            },
            {
                "filename": "protection_settings_f4.pdf",
                "title": "CUSC Appendix F4 — Protection Settings Schedule",
                "subtitle": "Thornholme 400 kV connection to Creyke Beck",
                "ref": {
                    "Connection point": "Creyke Beck 400 kV",
                    "Voltage": "400 kV",
                    "Scheme": "Dual-redundant distance + backup",
                    "Issued by": "Thornholme Renewables Ltd (protection engineer)",
                },
                "sections": [
                    {
                        "heading": "1. Protection philosophy",
                        "paras": [
                            "Main protection is provided by dual-redundant numerical distance "
                            "relays on independent DC supplies and independent VT/CT cores. "
                            "Backup is provided by directional earth-fault and overcurrent "
                            "protection. Breaker-fail protection initiates busbar zone "
                            "clearance.",
                        ],
                    },
                    {
                        "heading": "2. Fault-clearance performance",
                        "paras": [
                            "The total fault-clearance time at the point of connection is 80 ms "
                            "for a three-phase fault, within the NESO Creyke Beck zone "
                            "requirement of 100 ms. The settings are co-ordinated with NESO's "
                            "downstream zone-2 reach to maintain grading margins.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Schedule F4 — Relay settings",
                    "columns": ["Function", "Stage / zone", "Setting", "Time"],
                    "rows": [
                        ["Distance (main 1)", "Zone 1", "80% of line", "instantaneous"],
                        ["Distance (main 1)", "Zone 2", "120% of line", "350 ms"],
                        ["Distance (main 2)", "Zone 1", "80% of line", "instantaneous"],
                        ["Directional E/F (backup)", "—", "0.2 In", "500 ms"],
                        ["Overcurrent (backup)", "—", "1.2 In", "800 ms"],
                        ["Breaker fail", "—", "stub", "150 ms"],
                        ["Total clearance (3-ph)", "—", "—", "80 ms"],
                    ],
                },
            },
        ],
    },
    # ================================================================== TX DEM
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
                "ref": {
                    "Landlord": "Thurrock Gateway Developments Ltd",
                    "Tenant": "Aldgate Digital Infrastructure plc",
                    "Property": "12.1 ha at Aldgate Park, Thurrock, RM18 8RH",
                    "Title number": "EX998877 (leasehold, registered)",
                    "Term commencement": "1 January 2026",
                },
                "sections": [
                    {
                        "heading": "1. Demise and term",
                        "paras": [
                            "1.1 The Landlord demises the Property to the Tenant for a term of "
                            "thirty-five (35) years from 1 January 2026, granting exclusive "
                            "possession of the land registered under title EX998877 (12.1 "
                            "hectares).",
                            "1.2 The Lease is registered at HM Land Registry. It contains no "
                            "break clause exercisable by the Landlord before year 25; the "
                            "Tenant holds a tenant-only break at year 25 on twelve months' "
                            "notice.",
                        ],
                    },
                    {
                        "heading": "2. Permitted use",
                        "paras": [
                            "2.1 The permitted use is a data centre and ancillary plant "
                            "including on-site electrical infrastructure, transformers, and "
                            "standby generation, together with associated offices and security "
                            "facilities.",
                        ],
                    },
                    {
                        "heading": "3. Rent and review",
                        "paras": [
                            "3.1 The initial rent is £1.65m per annum, reviewed every fifth "
                            "year to open market value on an upward-only basis.",
                        ],
                    },
                    {
                        "heading": "4. Tenant and landlord covenants",
                        "paras": [
                            "4.1 The Tenant covenants to repair, insure, and comply with all "
                            "statutory requirements, and to permit the Landlord's grid and "
                            "utility easements. The Landlord covenants for quiet enjoyment and "
                            "to procure the grant of necessary wayleaves for the connection "
                            "works.",
                        ],
                    },
                    {
                        "heading": "5. Alienation and grid works",
                        "paras": [
                            "5.1 The Tenant may grant easements and wayleaves to the network "
                            "operator and the DNO for the connection and metering equipment "
                            "without the Landlord's consent, such rights to survive "
                            "determination of the Lease.",
                        ],
                    },
                ],
                "execution": [
                    "Executed as a deed by Thurrock Gateway Developments Ltd ...................",
                    "Executed as a deed by Aldgate Digital Infrastructure plc ...................",
                ],
            },
            {
                "filename": "planning_status_letter.pdf",
                "title": "Planning Status Letter — Thurrock Council",
                "subtitle": "Re: proposed data-centre campus at Aldgate Park",
                "ref": {
                    "From": "Development Management, Thurrock Council",
                    "To": "Aldgate Digital Infrastructure plc",
                    "Our ref": "TC/SCR/2026/0488",
                    "Date": "22 April 2026",
                    "Subject": "Planning status — Aldgate Park",
                },
                "sections": [
                    {
                        "heading": "1. Purpose of this letter",
                        "paras": [
                            "This letter confirms, at the applicant's request, the current "
                            "planning status of the proposed development at Aldgate Park as "
                            "recorded on the Council's planning register.",
                        ],
                    },
                    {
                        "heading": "2. Current status",
                        "paras": [
                            # DEFICIENCY: only an EIA screening request submitted; no application, no consent.
                            "2.1 An EIA screening request under the Town and Country Planning "
                            "(Environmental Impact Assessment) Regulations 2017 was received by "
                            "the Local Planning Authority on 14 April 2026 (ref. "
                            "TC/SCR/2026/0488).",
                            "2.2 A formal planning application has not yet been submitted, and "
                            "no planning permission has been granted to date. The Council holds "
                            "no extant consent for the data-centre campus.",
                        ],
                    },
                    {
                        "heading": "3. Next steps and caveat",
                        "paras": [
                            "3.1 The Council anticipates issuing a screening opinion within the "
                            "statutory period. The applicant is advised that this letter records "
                            "a pre-application screening only and must not be relied upon as "
                            "evidence of planning consent or of any resolution to grant consent.",
                        ],
                    },
                ],
            },
            {
                "filename": "anchor_tenant_heads_of_terms.pdf",
                "title": "Heads of Terms — Anchor Tenancy",
                "subtitle": "SUBJECT TO CONTRACT — NON-BINDING",
                "ref": {
                    "Party A": "Aldgate Digital Infrastructure plc",
                    "Party B": "[Cloud Provider] (name redacted under NDA)",
                    "Status": "Subject to contract; non-binding",
                    "Date": "28 April 2026",
                },
                "sections": [
                    {
                        "heading": "1. Status of this document",
                        "paras": [
                            "1.1 These Heads of Terms record the parties' current intentions in "
                            "relation to a prospective anchor tenancy and are expressly SUBJECT "
                            "TO CONTRACT and NON-BINDING. They create no legally binding "
                            "obligation on either party other than the confidentiality and "
                            "exclusivity provisions at clause 5.",
                        ],
                    },
                    {
                        "heading": "2. Indicative commitment",
                        "paras": [
                            "2.1 The parties envisage an anchor tenancy of up to 70% of "
                            "available IT capacity, subject to the negotiation and execution of "
                            "a definitive lease and service agreement, and to the tenant's "
                            "internal investment approval.",
                            "2.2 Indicative term: 15 years with two 5-year extensions. Pricing, "
                            "service levels, and power-availability guarantees remain to be "
                            "agreed.",
                        ],
                    },
                    {
                        "heading": "3. Conditions to a binding agreement",
                        "paras": [
                            "3.1 Any binding commitment is conditional on (a) board approval by "
                            "both parties; (b) confirmation of a firm grid connection date; and "
                            "(c) completion of technical due diligence on the campus design.",
                        ],
                    },
                    {
                        "heading": "4. No reliance",
                        "paras": [
                            "4.1 Either party may withdraw at any time before execution of the "
                            "definitive agreements without liability. Neither party shall "
                            "represent to any third party that a binding tenancy exists.",
                        ],
                    },
                ],
            },
            {
                "filename": "financial_statement.pdf",
                "title": "Statement of Financial Position",
                "subtitle": "Aldgate Digital Infrastructure plc — year ended 31 December 2025",
                "ref": {
                    "Company": "Aldgate Digital Infrastructure plc",
                    "Auditor": "Pennington Audit LLP",
                    "Security facility": "£24m on-demand guarantee (HSBC)",
                    "Basis": "Audited, abridged",
                },
                "sections": [
                    {
                        "heading": "1. Funding position",
                        "paras": [
                            "Cash and committed facilities of £150m are available for the first "
                            "development phase. A £24m on-demand guarantee facility has been "
                            "confirmed by HSBC for the purpose of the CUSC Section 15 user "
                            "commitment.",
                        ],
                    },
                    {
                        "heading": "2. Auditor's opinion",
                        "paras": [
                            "In our opinion the financial statements give a true and fair view "
                            "of the company's affairs as at 31 December 2025. The opinion is "
                            "unqualified.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Statement of financial position (£m)",
                    "columns": ["Item", "2025", "2024"],
                    "rows": [
                        ["Total assets", "640", "470"],
                        ["Total liabilities", "(230)", "(180)"],
                        ["Net assets", "410", "290"],
                        ["Cash + committed facilities", "150", "110"],
                        ["Guarantee facility (HSBC)", "24", "—"],
                    ],
                },
            },
        ],
    },
    # ================================================================== TX STO
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
                "title": "Single-Line Diagram & Equipment Schedule",
                "subtitle": "Pennine BESS — 200 MW / 800 MWh to 275 kV Stalybridge",
                "ref": {
                    "Connection point": "Stalybridge 275 kV busbar",
                    "Grid transformer": "200 MVA, 275/33 kV",
                    "Inverters": "40 x 5 MW grid-forming",
                    "Drawing ref": "PN-SLD-11, Rev B",
                },
                "sections": [
                    {
                        "heading": "1. Connection arrangement",
                        "paras": [
                            "The site connects to the 275 kV busbar at Stalybridge via a 200 "
                            "MVA 275/33 kV grid transformer and a 33 kV switchboard. The "
                            "metering point is at the 275 kV connection.",
                        ],
                    },
                    {
                        "heading": "2. Power conversion",
                        "paras": [
                            "Power conversion is by 40 x 5 MW grid-forming inverters arranged "
                            "in 8 blocks, each block with its own 33/0.69 kV transformer. The "
                            "inverter fleet is rated for symmetric bidirectional operation at "
                            "200 MW.",
                        ],
                    },
                    {
                        "heading": "3. Export limitation note",
                        "paras": [
                            # Note: SLD transformer rated 200 MVA but TEC export limited to 150 MW per capacity reg.
                            "Although the grid transformer and inverter fleet are each rated to "
                            "200 MVA / 200 MW, export at the metering point is constrained by "
                            "the site controller to the registered Transmission Entry Capacity. "
                            "The registered TEC value should be read from the capacity-"
                            "registration form, with which this diagram must be reconciled.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Equipment rating schedule",
                    "columns": ["Equipment", "Quantity", "Unit rating", "Aggregate"],
                    "rows": [
                        ["Grid transformer 275/33 kV", "1", "200 MVA", "200 MVA"],
                        ["Inverter (grid-forming)", "40", "5 MW", "200 MW"],
                        ["Block transformer 33/0.69 kV", "8", "25 MVA", "200 MVA"],
                        ["Battery (LFP)", "—", "—", "800 MWh"],
                        ["Site controller export cap", "1", "set to TEC", "150 MW"],
                    ],
                },
            },
            {
                "filename": "land_lease_agreement.pdf",
                "title": "Lease — Land adjacent to Stalybridge 275 kV",
                "subtitle": "Pennine Flexible Power Ltd",
                "ref": {
                    "Landlord": "Tame Valley Industrial Estates Ltd",
                    "Tenant": "Pennine Flexible Power Ltd",
                    "Property": "4.0 ha on Plan PN-RL-02, adjacent to Stalybridge 275 kV",
                    "Term": "25 years from completion (+10-year tenant option)",
                },
                "sections": [
                    {
                        "heading": "1. Demise and term",
                        "paras": [
                            "1.1 The Landlord demises the Property to the Tenant for a term of "
                            "twenty-five (25) years from completion, with a tenant-only option "
                            "to renew for a further ten (10) years on the same terms save as to "
                            "rent.",
                        ],
                    },
                    {
                        "heading": "2. Demised area and permitted use",
                        "paras": [
                            "2.1 The demised area extends to 4.0 hectares as shown on Plan "
                            "PN-RL-02. The permitted use is a battery energy storage system and "
                            "associated electrical connection works, including the grid "
                            "transformer compound and control building.",
                        ],
                    },
                    {
                        "heading": "3. Grid easements",
                        "paras": [
                            "3.1 The Tenant is granted, and may grant onward to the network "
                            "operator, all easements necessary for the 275 kV connection, "
                            "cabling, and metering, to survive determination of this Lease.",
                        ],
                    },
                ],
                "execution": [
                    "Executed as a deed by Tame Valley Industrial Estates Ltd ...................",
                    "Executed as a deed by Pennine Flexible Power Ltd ...........................",
                ],
            },
        ],
    },
    # ================================================================== DX GEN
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
                "ref": {
                    "Connection point": "Greenholt 33 kV primary busbar",
                    "Export capacity": "24 MVA",
                    "Import (auxiliary)": "0.5 MVA",
                    "Drawing ref": "GH-SLD-04, Rev A",
                },
                "sections": [
                    {
                        "heading": "1. Array arrangement",
                        "paras": [
                            "The PV array comprises 6 x 4 MW blocks, each with a 4 MVA 0.69/33 "
                            "kV transformer, combined onto a 33 kV switchboard.",
                        ],
                    },
                    {
                        "heading": "2. Point of connection",
                        "paras": [
                            "A single point of connection is made to the DNO 33 kV busbar at "
                            "Greenholt primary via a metered circuit breaker fitted with "
                            "interface protection. Maximum export 24 MVA; site auxiliary import "
                            "0.5 MVA.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Block schedule",
                    "columns": ["Block", "DC rating", "Inverter", "Transformer"],
                    "rows": [
                        ["B1-B6 (each)", "4.6 MWp", "4 MW Sungrow", "4 MVA 0.69/33 kV"],
                        ["Site total", "27.6 MWp", "24 MW AC", "24 MVA export"],
                    ],
                },
            },
            {
                "filename": "protection_settings.pdf",
                "title": "Interface Protection Settings Schedule",
                "subtitle": "Greenholt Solar Park — 33 kV point of connection",
                "ref": {
                    "Point of connection": "Greenholt 33 kV",
                    "Scheme": "G99 interface protection",
                    "Standard": "ENA G99 Issue 1, Table 10.1",
                    "Issued by": "Severn EPC Ltd",
                },
                "sections": [
                    {
                        "heading": "1. Scope",
                        "paras": [
                            "This schedule lists the interface-protection settings applied at "
                            "the 33 kV point of connection. The voltage and frequency elements "
                            "are co-ordinated with the DNO network protection.",
                        ],
                    },
                    {
                        "heading": "2. Loss-of-mains note",
                        "paras": [
                            # DEFICIENCY: no loss-of-mains / RoCoF or vector-shift anti-islanding element listed.
                            "2.1 The loss-of-mains (RoCoF) element and its stability setting are "
                            "to be confirmed at the commissioning stage and are NOT included in "
                            "this schedule. No vector-shift or RoCoF setting is therefore "
                            "specified in the table below.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Settings table (as submitted)",
                    "columns": ["Function", "Stage", "Setting", "Time delay"],
                    "rows": [
                        ["Undervoltage U<", "Stage 1", "-13%", "2.5 s"],
                        ["Undervoltage U<", "Stage 2", "-20%", "0.5 s"],
                        ["Overvoltage U>", "Stage 1", "+10%", "1.0 s"],
                        ["Overvoltage U>", "Stage 2", "+13%", "0.5 s"],
                        ["Underfrequency f<", "Stage 1", "47.5 Hz", "20 s"],
                        ["Underfrequency f<", "Stage 2", "47.0 Hz", "0.5 s"],
                        ["Overfrequency f>", "Stage 1", "51.5 Hz", "90 s"],
                        ["Overfrequency f>", "Stage 2", "52.0 Hz", "0.5 s"],
                        ["Loss of mains (RoCoF)", "—", "not set", "TBC at commissioning"],
                    ],
                },
            },
            {
                "filename": "type_test_certificate.pdf",
                "title": "Type Test Certificate — Sungrow SG3600UD-MV",
                "subtitle": "ENA Engineering Recommendation G99 compliance",
                "ref": {
                    "Equipment": "Sungrow SG3600UD-MV power unit",
                    "Standard": "ENA G99 Issue 1",
                    "Certificate ref": "SGR-G99-2024-0417",
                    "Laboratory": "Accredited test laboratory (UKAS)",
                },
                "sections": [
                    {
                        "heading": "1. Certification statement",
                        "paras": [
                            "This certifies that the Sungrow SG3600UD-MV power unit has been "
                            "tested in accordance with the type-test requirements of ENA "
                            "Engineering Recommendation G99 Issue 1.",
                        ],
                    },
                    {
                        "heading": "2. Verified capabilities",
                        "paras": [
                            "Verified capabilities: reactive power capability across the "
                            "required range; voltage ride-through to the G99 profile; frequency "
                            "response (LFSM-O and LFSM-U); and correct operation of protection "
                            "functions.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Test results summary",
                    "columns": ["Test", "Requirement", "Result"],
                    "rows": [
                        ["Reactive capability", "0.95 lead/lag", "Pass"],
                        ["Voltage ride-through", "G99 profile", "Pass"],
                        ["Frequency response", "LFSM-O / LFSM-U", "Pass"],
                        ["Protection operation", "Table 10.1", "Pass"],
                    ],
                },
            },
        ],
    },
    # ================================================================== DX STO
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
                "ref": {
                    "Connection point": "DNO 11 kV ring main unit",
                    "Inverter skids": "4 x 2 MW inverter-transformer",
                    "Charge path": "Grid-charging path provided",
                    "Drawing ref": "RV-SLD-02, Rev A",
                },
                "sections": [
                    {
                        "heading": "1. Connection arrangement",
                        "paras": [
                            "Four 2 MW inverter-transformer skids are combined onto an 11 kV "
                            "switchboard, connected to the DNO 11 kV network via a metered ring "
                            "main unit. The site auxiliary supply is taken from the LV board of "
                            "skid 1.",
                        ],
                    },
                    {
                        "heading": "2. Bidirectional flow",
                        "paras": [
                            "A grid-charging path is provided: the BESS can import from the 11 "
                            "kV network as well as export. Both import and export are metered at "
                            "the ring main unit.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Skid schedule",
                    "columns": ["Skid", "Inverter", "Transformer", "Mode"],
                    "rows": [
                        ["S1-S4 (each)", "2 MW", "2 MVA 0.4/11 kV", "bidirectional"],
                        ["Site total", "8 MW", "8 MVA", "import + export"],
                    ],
                },
            },
            {
                "filename": "type_test_certificate.pdf",
                "title": "Type Test Certificate — Power Electronics FS3450",
                "subtitle": "ENA Engineering Recommendation G99 Issue 2",
                "ref": {
                    "Equipment": "Power Electronics FS3450 inverter",
                    "Standard": "ENA G99 Issue 2",
                    "Certificate ref": "PE-G99v2-2025-1180",
                    "Control mode": "Grid-following (current-source)",
                },
                "sections": [
                    {
                        "heading": "1. Certification statement",
                        "paras": [
                            "This certifies that the inverter has been type-tested in "
                            "accordance with ENA Engineering Recommendation G99 Issue 2.",
                        ],
                    },
                    {
                        "heading": "2. Control mode",
                        "paras": [
                            # DEFICIENCY: certificate states grid-following control mode.
                            "2.1 Control mode: grid-following (current-source) operation. The "
                            "unit was NOT tested for grid-forming (voltage-source) operation, "
                            "and no virtual-inertia capability is certified under this report.",
                        ],
                    },
                    {
                        "heading": "3. Verified capabilities",
                        "paras": [
                            "Verified in grid-following mode: low-voltage ride-through (LVRT); "
                            "reactive capability; and frequency response. Grid-forming "
                            "behaviour, synthetic inertia, and fault-level contribution as a "
                            "voltage source are outside the scope of this certificate.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Test results summary",
                    "columns": ["Test", "Mode", "Result"],
                    "rows": [
                        ["LVRT", "grid-following", "Pass"],
                        ["Reactive capability", "grid-following", "Pass"],
                        ["Frequency response", "grid-following", "Pass"],
                        ["Grid-forming / inertia", "—", "Not tested"],
                    ],
                },
            },
            {
                "filename": "protection_settings.pdf",
                "title": "Interface Protection Settings — Riverside BESS",
                "subtitle": "11 kV point of connection",
                "ref": {
                    "Point of connection": "11 kV ring main unit",
                    "Standard": "ENA G99 Issue 2",
                    "Loss of mains": "RoCoF 1.0 Hz/s, 0.5 s",
                },
                "sections": [
                    {
                        "heading": "1. Anti-islanding",
                        "paras": [
                            "Loss-of-mains protection is provided by a RoCoF element set at "
                            "1.0 Hz/s with a 0.5 s confirmation time, co-ordinated with the DNO "
                            "11 kV scheme.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Settings table",
                    "columns": ["Function", "Setting", "Time delay"],
                    "rows": [
                        ["Loss of mains (RoCoF)", "1.0 Hz/s", "0.5 s"],
                        ["Undervoltage U<", "-13%", "2.5 s"],
                        ["Undervoltage U<", "-20%", "0.5 s"],
                        ["Overvoltage U>", "+10%", "1.0 s"],
                        ["Overvoltage U>", "+13%", "0.5 s"],
                        ["Underfrequency f<", "47.5 Hz", "20 s"],
                        ["Underfrequency f<", "47.0 Hz", "0.5 s"],
                        ["Overfrequency f>", "51.5 Hz", "90 s"],
                    ],
                },
            },
        ],
    },
    # ================================================================== DX MIX
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
                "ref": {
                    "Connection point": "Shared 33 kV metered busbar",
                    "PV array": "15 MW",
                    "BESS": "10 MW / 20 MWh",
                    "Coupling": "AC-coupled on shared bus",
                    "Drawing ref": "MB-SLD-06, Rev B",
                },
                "sections": [
                    {
                        "heading": "1. Shared connection",
                        "paras": [
                            "The PV array (15 MW) and BESS (10 MW / 20 MWh) are combined onto a "
                            "common 33 kV switchboard sharing a single metered point of "
                            "connection. A site controller enforces the combined 15 MW export "
                            "limit.",
                        ],
                    },
                    {
                        "heading": "2. BESS coupling and charge path",
                        "paras": [
                            # DEFICIENCY: BESS sits on the shared AC bus with a closed grid-import path.
                            "2.1 The BESS inverters are connected to the shared 33 kV AC bus "
                            "through a bidirectional breaker. With the PV array offline, the "
                            "BESS can charge from the grid through this path; there is no "
                            "DC-coupling that would physically restrict charging to PV only.",
                            "2.2 No interlock is shown that would prevent grid import to the "
                            "BESS when PV generation is zero.",
                        ],
                    },
                ],
                "schedule": {
                    "title": "Connection schedule",
                    "columns": ["Asset", "Rating", "Coupling", "Charge source"],
                    "rows": [
                        ["PV array", "15 MW", "AC, shared bus", "—"],
                        ["BESS", "10 MW / 20 MWh", "AC, shared bus", "PV or grid (no interlock)"],
                        ["Export limit (controller)", "15 MW firm", "metered POC", "—"],
                    ],
                },
            },
            {
                "filename": "control_philosophy.pdf",
                "title": "Site Control Philosophy — Meadowbank",
                "subtitle": "Dispatch and curtailment logic",
                "ref": {
                    "Site controller": "Master PPC with ANM interface",
                    "Firm export limit": "15 MW",
                    "ANM response time": "2 s",
                },
                "sections": [
                    {
                        "heading": "1. Dispatch priority",
                        "paras": [
                            "Priority 1: export available PV up to the 15 MW firm limit. "
                            "Priority 2: charge the BESS from surplus PV above the firm limit. "
                            "Priority 3: discharge the BESS into the evening peak within the "
                            "firm limit.",
                        ],
                    },
                    {
                        "heading": "2. Curtailment",
                        "paras": [
                            "The controller responds to DNO ANM curtailment signals within two "
                            "seconds, reducing combined export to the instructed set-point. "
                            "Curtailment is shared between PV and BESS to preserve state of "
                            "charge where possible.",
                        ],
                    },
                    {
                        "heading": "3. Charge-source control (software)",
                        "paras": [
                            "3.1 The control philosophy states an intention to charge the BESS "
                            "from surplus PV. This is a software set-point only; the physical "
                            "single-line arrangement does not preclude grid charging, and the "
                            "two documents should be read together when assessing the "
                            "export-only declaration.",
                        ],
                    },
                ],
            },
        ],
    },
]
