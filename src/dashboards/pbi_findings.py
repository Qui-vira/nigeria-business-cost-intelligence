"""The explanation layer: findings, framing and archetype guidance, in business language.

WHAT THIS FILE IS FOR
---------------------
Both dashboards read their words from here, so Excel and Power BI cannot drift apart. The
previous version organised the experience around DATASETS - Fuel, Transport, CPI - which
left a business owner looking at a correct chart and still asking "what am I supposed to
learn from this?". This file organises it around BUSINESS QUESTIONS instead, and states the
answer in plain English before any chart is shown.

THE FRAMING THAT GOVERNS EVERYTHING BELOW
-----------------------------------------
NBCI measures part of the external operating-cost environment. It does NOT measure business
attractiveness and it does NOT measure profitability. A jurisdiction with a lower measured
diesel price is not thereby "a better place to do business": revenue opportunity, customer
demand, purchasing power, supplier access, infrastructure, supply-chain length, market
concentration and competitive friction are all absent from this dataset and any of them can
outweigh an input-cost difference. So no string in this file may equate low cost with high
profit, and no string may name a "best" or "worst" jurisdiction.

EVERY FIGURE IS SOURCED from the committed evidence under `outputs/analysis/` and the two
committed reports. Nothing here is invented, and nothing is stated more strongly than the
evidence it cites.

LANGUAGE RULE, BINDING AND MACHINE-CHECKED
------------------------------------------
The dataset holds no company cost shares, margins, pass-through ability or revenue, so
nothing here instructs a business to act. Review language only - review, investigate,
compare, measure, reassess, examine, put on the agenda. `validate_excel_dashboard.py`
layer D and `pbi_validate.ps1` section D fail the build on a prescriptive instruction.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# THE CORE QUESTION AND THE ONE-LINE DESCRIPTION.
#
# These two strings are the project's positioning. Everything else must stay
# inside them. An earlier version asked "how are the COSTS OF DOING BUSINESS
# changing across Nigerian states, and what should different businesses DO about
# it?" - a question this project cannot answer and never could, for three
# reasons that are worth restating every time someone is tempted to shorten it:
#
#   1. NBCI measures nine bought-in costs, not the full cost of doing business.
#      There is no rent, no wages, no land, no taxes, no levies, no stock.
#   2. Not every source is state-level. Exchange rate is national, food is zone
#      grain, electricity is DisCo grain. Location comparison is valid for SOME
#      costs, not all of them.
#   3. Telling a specific company what to DO needs that company's own cost
#      shares, margins, pass-through ability and market position. None of that
#      is in this dataset, so the honest output is what to INVESTIGATE.
# ---------------------------------------------------------------------------
CORE_QUESTION = (
    "How are key external business cost pressures changing across Nigeria, how do they "
    "differ by location where the data supports it, which types of businesses are they "
    "likely to matter more for, and what should managers monitor or investigate in "
    "response?"
)

SIMPLE_DESCRIPTION = (
    "NBCI shows how important external business costs are changing across Nigeria, which "
    "types of businesses those costs are likely to matter more for, and what managers "
    "should investigate to protect their margins."
)


# ---------------------------------------------------------------------------
# THE CAPABILITY BOUNDARY, carried as DATA so both tools show the same list and
# neither can quietly widen it. Every string is a claim this project can defend
# today, or one it deliberately refuses to make today.
# ---------------------------------------------------------------------------
CAN_DO = [
    "Track selected external business cost pressures",
    "Show how those pressures change over time",
    "Compare locations where the source data supports geographic comparison",
    "Identify which types of business a particular cost pressure is likely to matter more for",
    "Explain why a cost movement may matter to day-to-day operations",
    "Show what management should monitor, measure, compare or investigate",
    "Provide evidence for further business analysis",
]

CANNOT_DO = [
    "Determine whether a specific company is profitable",
    "Predict whether a company will lose money",
    "Identify the universally best jurisdiction to operate in",
    "Claim that a cheaper jurisdiction is a better business location",
    "Calculate the effect of a cost change on a specific company's margin",
    "Prescribe company-specific actions without financial and market data from that company",
]

WHAT_IT_WOULD_TAKE = (
    "What NBCI delivers today is external cost intelligence, a read on which kinds of "
    "business each cost is likely to matter more for, and guidance on what to investigate. "
    "Turning that into company-specific decision support would need "
    "things this project does not hold: a company's own financial data, its market "
    "assumptions and scenario modelling built on both. That is a possible later version, not "
    "something this one does."
)


# ---------------------------------------------------------------------------
# THE FRAMING. This appears on the first page of both tools, and again on the
# location page where the misreading is most likely.
# ---------------------------------------------------------------------------
WHAT_THIS_IS = (
    "NBCI measures part of what it COSTS to operate in each of Nigeria's 37 jurisdictions - "
    "the 36 states plus the Federal Capital Territory. It covers nine costs a business buys "
    "in, such as fuel and transport fares, plus inflation rates, taken from eight official "
    "government datasets."
)

WHAT_THIS_IS_NOT = (
    "It does NOT measure how attractive a jurisdiction is for business, and it does NOT "
    "measure profitability. A lower measured fuel or transport cost does not make a place "
    "a better location, and a higher one does not make it worse."
)

WHY_NOT = (
    "Whether a location suits a business depends on what it can earn there as much as on "
    "what it pays. That means revenue opportunity, customer demand, purchasing power, market "
    "size and how much competition it faces, plus rent, wages, supplier access, "
    "infrastructure, supply-chain length, its own margins and how it is set up to operate. "
    "None of that is in this dataset. A jurisdiction with higher measured costs can easily be "
    "the more profitable one, and a cheap one can be a poor place to trade."
)

THE_EQUATION = [
    ("Revenue opportunity", "demand, purchasing power, volume, competition",
     "NOT measured here"),
    ("Operating costs", "nine costs a business buys in, plus inflation rates",
     "PARTLY measured here - this is the NBCI slice"),
    ("Location advantages and frictions", "infrastructure, supplier access, supply-chain length",
     "NOT measured here"),
    ("Company economics", "rent, wages, margins, inventory, pass-through ability",
     "NOT measured here"),
]

ONE_LINE = (
    "NBCI helps a business understand cost pressure. It does not by itself tell them which "
    "jurisdiction will be most profitable."
)


# ---------------------------------------------------------------------------
# THE HEADLINE FINDINGS.
#
# Six parts each, in the order a reader needs them:
#   found       what the validated result actually says
#   matters     the possible business consequence
#   who         which business types or operating models should look
#   review      a management question or internal metric worth investigating
#   evidence    the committed file behind the claim
#   boundary    what this cannot prove
# ---------------------------------------------------------------------------
FINDINGS = [
    dict(
        rank=1,
        question="Does a falling fuel price reach my transport costs?",
        headline="Petrol falling does not automatically make transport cheaper",
        found=(
            "In 81 jurisdiction-month pairs where petrol was CHEAPER than a year earlier, "
            "fares still rose: okada, water and air in 100% of observations, intracity bus "
            "in 98.8%, intercity bus in 84.0%."),
        matters=(
            "Fares move up with fuel and then stay up. A business that budgeted for "
            "transport costs to ease when the pump price eased would not have seen that "
            "saving arrive. Over four usable year-on-year months okada fares rose a median "
            "+50.7% while headline inflation ran +16.2% - a gap of 35.6 percentage points."),
        who=(
            "Anyone who buys movement rather than fuel: last-mile delivery, staff commuting "
            "and transport allowances, field sales and service teams, and any business whose "
            "customers travel to reach it."),
        review=(
            "Compare what you actually paid for delivery and staff transport over the last "
            "year against the pump price over the same months. If your allowances are "
            "indexed to CPI alone, examine whether that has kept pace with observed fares."),
        evidence="f29_fare_ratchet_summary.csv · d5/d6_fare_vs_cpi",
        boundary=(
            "These are PASSENGER fares, not freight rates - treating intercity bus as a "
            "haulage proxy is an assumption, not a measurement. No causal claim: petrol is "
            "one observed input among many, and the observations fall in only four months, "
            "so they are not independent events."),
    ),
    dict(
        rank=2,
        question="Which cost moved most, and who is it likely to matter more for?",
        headline="Diesel-dependent operations deserve closer attention than most",
        found=(
            "Diesel rose a median +158.2% from its 2025-09 trough to 2026-05 and rose in ALL "
            "37 jurisdictions - the slowest was +115.1%. It also carries the highest exposure "
            "effect on total cost of anything measured here: for every 1% of your spending "
            "that goes on diesel, a doubling moves your total cost by 0.66%."),
        matters=(
            "A cost that more than doubled matters in proportion to how much of it you buy. "
            "For an operation where diesel is a large share - haulage, cold chain, long "
            "generator hours - this is a material move. For one where it is a small share it "
            "may be close to irrelevant. The dataset cannot tell which you are."),
        who=(
            "Logistics and delivery fleets, cold-chain operators including pharmacy and food "
            "retail, manufacturers running generators as baseload, and any business whose "
            "premises depend on backup power for long hours."),
        review=(
            "Measure your own diesel dependence before drawing any conclusion: litres per "
            "month, litres per kilometre or per operating hour, and diesel as a share of "
            "total operating cost. Then work out what that share means for you."),
        evidence="f31_shock_trough_to_latest.csv · d7_exposure_sensitivity.csv",
        boundary=(
            "The multiplier converts a price move into a total-cost impact only once you "
            "supply your own cost share, which this dataset does not hold. It says nothing "
            "about whether you can pass the increase on."),
    ),
    dict(
        rank=3,
        question="How much does location actually change what I pay?",
        headline="Location changes some costs a great deal and others barely at all",
        found=(
            "Across the 37 jurisdictions, water transport varies 6.91x between the lowest and "
            "highest measured value and okada 2.32x. Petrol varies 1.14x and diesel 1.29x - "
            "the entire national petrol spread is ₦195.16 per litre."),
        matters=(
            "Comparing two locations on a single cost can mislead badly. On fuel the "
            "difference is close to noise; on local mobility it is large and it persists. A "
            "comparison built on the wrong cost family will point the wrong way."),
        who=(
            "Any business with a genuinely open siting decision, and any business setting "
            "standing supplier or depot preferences on the assumption that location delivers "
            "a fuel saving."),
        review=(
            "Identify which cost families you actually buy in volume, and compare candidate "
            "locations on those - naming the specific metric, not 'cost' in general. Examine "
            "whether a siting assumption in your plan rests on a cost that barely varies."),
        evidence="d8_location_value_by_cost.csv · f05_dispersion_summary.csv",
        boundary=(
            "LOWER MEASURED COST IS NOT A BETTER BUSINESS LOCATION. This compares input "
            "prices only. Demand, purchasing power, supplier access and competition are not "
            "in this dataset and routinely outweigh an input-cost difference. For five of the "
            "nine costs the order of jurisdictions keeps changing, so no jurisdiction is named "
            "as the cheapest over time. Each single month's ranking is still valid."),
    ),
    dict(
        rank=4,
        question="Is running a generator a cost strategy or an insurance policy?",
        headline="Self-generation ran several times grid cost at the reference tariff",
        found=(
            "Diesel self-generation cost 3.9-5.2x the fixed July 2025 Band A reference tariff "
            "of ₦209.50/kWh, and was never cheaper than grid at any band or in any month of "
            "the series. Break-even needs diesel at ₦628.50/l against a cheapest observed "
            "₦1,266.33."),
        matters=(
            "Generator hours beyond genuinely unavoidable outage hours are a priced decision, "
            "not a neutral one. The multiple widened from 2.01x to 5.17x in eight months, so "
            "a comparison made a year ago is out of date."),
        who=(
            "Manufacturing and light production, pharmacy and any cold-chain retail, and "
            "offices or shops running long generator hours by habit rather than by measured "
            "need."),
        review=(
            "Read the service band off your own electricity bill and obtain the CURRENT "
            "tariff, then re-run the comparison. Measure actual outage hours and compare them "
            "against generator running hours. Before an inverter, battery or solar "
            "investment, compare payback against the grid tariff you actually pay."),
        evidence="d3_selfgen_vs_reference_tariff.csv · d4_selfgen_breakeven.csv",
        boundary=(
            "The tariff is a FIXED July 2025 cross-section, roughly ten months older than the "
            "diesel series - if tariffs have since risen the true multiples are smaller. "
            "DisCo territories are not jurisdictions, so no premises can be assigned a band "
            "from this data; it must be read off the bill."),
    ),
    dict(
        rank=5,
        question="Is there one state that is always the cheapest for a cost?",
        headline="For five of nine costs, the cheapest place keeps changing",
        found=(
            "For air travel, diesel, LPG 5 kg, LPG 12.5 kg and petrol, the cheapest place keeps "
            "changing. Across the 37 jurisdictions, which means the 36 states plus the Federal "
            "Capital Territory, a single month's price move is usually bigger than the whole gap "
            "between the cheapest and the dearest, so the order reshuffles. Each month's ranking "
            "is still a correct snapshot of that month. What the data cannot do is reliably name "
            "one jurisdiction as the cheapest OVER TIME. The other four costs - water transport, "
            "okada, intracity bus and intercity bus - do hold their order."),
        matters=(
            "A 'cheapest places' list taken from one month is a true picture of that month and a "
            "poor basis for a decision you will live with for years, because next month's list is "
            "different. A standing supplier or site preference built on those five costs is "
            "built on something that keeps moving."),
        who=(
            "Anyone choosing a supplier they intend to keep, and anyone building a shortlist of "
            "locations from a single month's price table."),
        review=(
            "Where the order keeps changing, look at volume and contract terms instead, because "
            "that is where the real lever is. Reassess any standing preference that was "
            "justified by a one-month price comparison."),
        evidence="f40_rank_stability.csv · v4_rank_stability.csv",
        boundary=(
            "This is about decisions that last, not about data quality. Every published monthly "
            "ranking is correct for its own month and remains a valid snapshot. What it will not "
            "support is a lasting location or sourcing choice based on that order."),
    ),
    dict(
        rank=6,
        question="Can I use the inflation rate in the news to plan my costs?",
        headline="Inflation slowed, but diesel and local fares kept climbing much faster",
        found=(
            "The inflation rate reported in the news - CPI all items, compared with the same "
            "month a year earlier - fell from a median 22.34% in February 2025 to 15.36% in "
            "April 2026, though not in a straight line. Over those same months the median "
            "diesel price rose 70.49%, and from its low point in September 2025 to May 2026 "
            "diesel rose 158.16%. In the four months where fares and inflation can be compared "
            "year on year, okada fares rose a median 50.66% and intracity bus fares 39.37%, "
            "against inflation of 16.23%. This is about those measured costs, not about "
            "everything a business buys."),
        matters=(
            "A business that raised its budgets or its staff transport allowances by the "
            "headline inflation rate would not have kept up with its diesel bill or its "
            "transport bill. What customers face is uneven too: food inflation ran from +1.67% "
            "to +32.67% across jurisdictions in April 2026, so one national pricing or stocking "
            "plan is hard to defend."),
        who=(
            "Anyone raising transport or cost allowances in line with the inflation rate, and "
            "retail or service businesses in several locations running one national pricing "
            "plan."),
        review=(
            "Compare the specific costs you actually buy against the inflation rate, rather "
            "than using the inflation rate in their place. If you operate in several "
            "jurisdictions, compare your own jurisdiction's food inflation against the middle "
            "value across all 37, which is 17.37%."),
        evidence=("f01_trend_primary_window.csv · f03_cpi_rates_by_month.csv · "
                  "f31_shock_trough_to_latest.csv · d6_fare_vs_cpi_summary.csv"),
        boundary=(
            "This compares the nine measured input costs with inflation. It says nothing about "
            "rent, wages, goods for resale, taxes or finance, so it is NOT a statement about a "
            "business's whole cost base. The windows differ and are not interchangeable: the "
            "inflation figures run February 2025 to April 2026, the diesel low-point figure "
            "runs September 2025 to May 2026, and the fare comparison uses only four months. "
            "CPI describes the CUSTOMER's cost pressure, not a business's cost base. CPI index "
            "LEVELS may never be compared between jurisdictions - only rates of change."),
    ),
]


# ---------------------------------------------------------------------------
# THE SIX ARCHETYPES.
#
# Five questions each, in the order a manager needs them:
#   costs     which NBCI costs matter to this type of business
#   signals   what the dataset currently shows for them
#   why       why those signals could matter OPERATIONALLY
#   review    what management should investigate inside its own company
#   needed    the company-specific data required before any actual decision
# ---------------------------------------------------------------------------
ARCHETYPES = [
    dict(
        order=1, archetype="Logistics / Delivery",
        metric_codes="DIESEL_PRICE_NGN_PER_LITRE|PETROL_PRICE_NGN_PER_LITRE|"
                     "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
        costs=(
            "Diesel and petrol as direct fuel, and inter-regional bus fares as the only "
            "movement price the dataset carries. Diesel is both the biggest mover here and "
            "the cost that does most to your total bill for every naira you spend on it."),
        signals=(
            "Diesel +158.2% from the 2025-09 trough to 2026-05, rising in all 37 "
            "jurisdictions. Its geographic spread is only 1.29x and its ranking is unstable. "
            "Intercity fares rose in 84.0% of the observations where petrol was cheaper "
            "year-on-year."),
        why=(
            "Two pressures that point in opposite directions. Fuel changes a lot over TIME and "
            "very little by PLACE - there is no depot siting that meaningfully "
            "changes the diesel price you pay. If you buy third-party haulage instead of "
            "burning your own fuel, the ratchet finding matters more than the pump price."),
        review=(
            "Measure litres per kilometre by vehicle class and fuel as a share of total "
            "operating cost. Examine your contract repricing and surcharge clauses: do they "
            "reference a fuel index, and over what lag? Review route mix and empty-running "
            "rate. Put a pricing review on the agenda when diesel is flagged ELEVATED (26.0%) "
            "or EXTREME (52.04%) in your jurisdiction - 2026-04 flagged EXTREME in 25 of 37 "
            "at once, which is a portfolio-wide condition rather than a route-by-route one."),
        needed=(
            "Litres per km by vehicle class · fuel as a share of total cost · contract "
            "repricing and surcharge clauses · route mix and empty-running rate · maintenance "
            "and tyre cost per km · driver pay structure · vehicle finance terms · insurance, "
            "tolls and security levies"),
        boundary=(
            "NBS publishes PASSENGER fares, not freight rates - every use of intercity bus as "
            "a haulage proxy is an assumption. No driver wages, tyres, spares, insurance, "
            "tolls, levies or vehicle finance are in this dataset, and no fuel-burn or route "
            "data. Diesel ends 2026-05."),
    ),
    dict(
        order=2, archetype="Pharmacy / Healthcare Retail",
        metric_codes="DIESEL_PRICE_NGN_PER_LITRE|PETROL_PRICE_NGN_PER_LITRE|"
                     "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY|TRANSPORT_OKADA_NGN_PER_JOURNEY|"
                     "CPI_ALL_ITEMS_YOY_PCT|CPI_FOOD_YOY_PCT",
        costs=(
            "Diesel for backup power and cold chain, local mobility for staff and customers, "
            "and CPI change rates as a read on the customer's own squeeze. The NERC band is "
            "DisCo grain and must be read off the bill, never inferred from location."),
        signals=(
            "Self-generation ran 3.9-5.2x the Band A reference tariff and was never cheaper "
            "than grid. Local fares rose while petrol fell. CPI food year-on-year ranged "
            "+1.67% to +32.67% across jurisdictions in 2026-04."),
        why=(
            "Cold chain makes uninterrupted power a clinical requirement, not a convenience, "
            "so the question is not 'generator or grid' but how many generator hours are "
            "genuinely unavoidable. Separately, discretionary health spend is demand-sensitive, "
            "and a squeeze that varies fivefold across jurisdictions makes one national "
            "pricing or stocking posture hard to defend."),
        review=(
            "Read the service band off your bill and obtain the current tariff, then re-run "
            "the comparison. Measure outage hours against generator running hours. Measure "
            "cold-chain load as a share of consumption. Compare your jurisdiction's CPI food "
            "year-on-year against the cross-jurisdiction median before reading a sales dip as "
            "an execution problem."),
        needed=(
            "Medicine and product ACQUISITION COSTS · rent · salaries · monthly kWh and the "
            "band letter from the bill · generator fuel burn per hour and load factor · "
            "measured outage hours · cold-chain load share · supplier terms and credit · "
            "inventory turnover · sales and gross margin by category · local customer demand"),
        boundary=(
            "THIS CANNOT CALCULATE OR INFER A PHARMACY'S PROFITABILITY, MARGIN OR VIABILITY. "
            "It describes the external operating-cost environment only. Every item in the "
            "list above is absent from this dataset. DisCo territories are not jurisdictions, "
            "so no premises can be assigned a tariff band from this data."),
    ),
    dict(
        order=3, archetype="Restaurant / Food Service",
        metric_codes="LPG_REFILL_5KG_NGN|LPG_REFILL_12_5KG_NGN|DIESEL_PRICE_NGN_PER_LITRE|"
                     "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
        costs=(
            "Cooking gas in both cylinder sizes - never averaged, they are different products "
            "- diesel for backup power, local mobility for staff and customers, and food "
            "inputs, which exist only at ZONE grain."),
        signals=(
            "LPG is the most volatile cost in the dataset: a typical monthly move of 7.2-7.8% "
            "and an upper quartile of 19-22%. Its jurisdiction ranking is unusable - monthly "
            "moves are about 2.1x the entire spread. Food inputs carry a 24-percentage-point "
            "North-South gradient, South East +12.49% above national and North West -11.30% "
            "below."),
        why=(
            "Volatility, not level, is what breaks a menu cost card: a cost that moves 20% in "
            "a quarter outruns a price list reviewed annually. And procurement geography "
            "matters for food at zone level while meaning nothing for LPG, so the two inputs "
            "call for different sourcing logic."),
        review=(
            "Measure LPG kilograms per month and cylinder mix. Put a menu cost-card review on "
            "the agenda when LPG 12.5 kg is flagged ELEVATED (26.70%) or EXTREME (29.55%) - it "
            "was EXTREME in 20 of 37 jurisdictions in 2025-11. For food inputs, compare at "
            "zone level and investigate actual supplier prices at your own location, which is "
            "the only way past the zone ceiling."),
        needed=(
            "LPG kg per month and cylinder mix · actual supplier prices at your own location · "
            "menu cost cards with ingredient weights · covers per day and seasonality · rent · "
            "wage bill · waste rate · water and packaging cost · local customer demand"),
        boundary=(
            "FOOD HAS NO JURISDICTION-LEVEL PRICES AT ALL - six zones only, so a Lagos "
            "restaurant inherits South West pricing averaged over six states. No rent, wages, "
            "water, waste or packaging. The LPG series ends 2026-04, one month before the "
            "fuels."),
    ),
    dict(
        order=4, archetype="Retail (non-food, shop-based)",
        metric_codes="DIESEL_PRICE_NGN_PER_LITRE|TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY|"
                     "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY|TRANSPORT_OKADA_NGN_PER_JOURNEY|"
                     "CPI_ALL_ITEMS_YOY_PCT|CPI_FOOD_YOY_PCT",
        costs=(
            "Overheads and the demand side: backup power, inbound movement, local mobility "
            "governing both staff commute and customer footfall, and the customer's own price "
            "pressure. Nothing here describes what a retailer BUYS."),
        signals=(
            "Consumer pressure differs sharply by jurisdiction - all-items year-on-year ranged "
            "+5.91% to +25.74% and food +1.67% to +32.67% in 2026-04, against medians of "
            "15.36% and 17.37%. Inbound movement rose: intercity bus +29.90% over the window."),
        why=(
            "Footfall and basket size respond to the customer's squeeze, and a squeeze that "
            "varies fivefold means a sales dip in one location may be demand compression "
            "rather than execution failure. Local mobility also governs whether customers can "
            "reach you cheaply, which is a siting consideration in a way fuel is not."),
        review=(
            "Compare your jurisdiction's CPI food year-on-year against the cross-jurisdiction "
            "median before reading a sales dip as an execution problem. Revisit inbound "
            "freight terms when intercity bus is flagged ELEVATED (10.19%) - 2026-03 was "
            "EXTREME in 21 of 37 jurisdictions. Use CPI CHANGE RATES only, never index levels."),
        needed=(
            "Wholesale invoices and category margins · rent and service charge by site · "
            "footfall and conversion by location · basket composition · staff cost by site · "
            "shrinkage · payment processing cost · actual inbound freight rates · local "
            "customer demand and competitor density"),
        boundary=(
            "WE HOLD NOTHING ON WHAT A RETAILER BUYS - no wholesale prices, no rent, no wages, "
            "no shrinkage, no payment costs. CPI describes the CUSTOMER's cost pressure, not "
            "the retailer's cost base; using it as a proxy for goods cost or wage settlements "
            "is unsupported. Intercity bus fare is a passenger fare, not a freight rate."),
    ),
    dict(
        order=5, archetype="Manufacturing / Light Production",
        metric_codes="DIESEL_PRICE_NGN_PER_LITRE|LPG_REFILL_12_5KG_NGN|LPG_REFILL_5KG_NGN",
        costs=(
            "Process and backup energy - diesel and LPG - measured against a DisCo-grain "
            "electricity benchmark. FX appears as national context only, never as a "
            "jurisdiction metric."),
        signals=(
            "Self-generation was never cheaper than grid at any band or month, and the multiple "
            "widened from 2.01x to 5.17x in eight months. The naira APPRECIATED 11.9% over the "
            "same period in which diesel rose 158%. Diesel and LPG growth are essentially "
            "unrelated across jurisdictions (rho = -0.22)."),
        why=(
            "Three operational consequences. The generator is outage insurance rather than "
            "baseload. An FX hedge would not have protected the energy budget, because the two "
            "moved in opposite directions. And because diesel and LPG do not co-move, a plant "
            "using both carries two independent risks and cannot use one to offset the other."),
        review=(
            "Measure monthly kWh and your load profile, and verify the band letter and the "
            "tariff actually paid. Compare measured outage hours against generator running "
            "hours, and treat hours beyond that as a priced decision. Examine whether grid "
            "reliability investment or band verification comes before buying generating "
            "capacity. Budget diesel and LPG as separate risks."),
        needed=(
            "Monthly kWh and load profile · the band letter and tariff actually paid · genset "
            "fuel burn and maintenance cost · measured outage hours and the cost of an "
            "unplanned stop · raw material invoices and import share · energy as a share of "
            "cost of production · plant, labour and land costs · order book and demand"),
        boundary=(
            "No industrial tariff schedule, no consumption data, no load profile. NERC is a "
            "single JULY 2025 CROSS-SECTION, not a tariff history, and cannot be assigned to a "
            "jurisdiction. No raw materials, plant, labour, land or import duty. The FX-diesel "
            "relationship compares two national series over 21 months and establishes NO "
            "CAUSAL CLAIM."),
    ),
    dict(
        order=6, archetype="Service Businesses (office-based)",
        metric_codes="TRANSPORT_OKADA_NGN_PER_JOURNEY|TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY|"
                     "DIESEL_PRICE_NGN_PER_LITRE|CPI_ALL_ITEMS_YOY_PCT|CPI_FOOD_YOY_PCT",
        costs=(
            "Local mobility for staff, backup power for the office, and the inflation rate any "
            "allowance is indexed to."),
        signals=(
            "Matched by jurisdiction and month over four usable year-on-year months, okada "
            "fares rose a median +50.66% against CPI all-items +16.23% - a gap of 35.64 "
            "percentage points, with fares above CPI in 98.6% of 148 observations. Intracity "
            "bus: +39.37% vs +16.23%, a 21.68-point gap, in 91.2%. Local mobility is the only "
            "cost family where jurisdiction choice is both large and persistent."),
        why=(
            "A transport allowance indexed only to CPI would have lagged observed fare growth, "
            "reducing the commuting purchasing power the allowance provides. That is a "
            "statement about the allowance against fares, NOT about total real pay. And for a "
            "business whose main location-sensitive cost is people moving locally, siting is a "
            "measurable lever in a way it is not for fuel-intensive operations."),
        review=(
            "Compare your allowance uprating mechanism against observed local fares rather "
            "than CPI alone - a CPI-only uprate lagged fare growth by 21.7 points (bus) to "
            "35.6 points (okada). Revisit allowances when intracity bus (11.23%) or okada "
            "(11.20%) is flagged ELEVATED. For siting, compare persistent positions rather "
            "than a single month, and name the mode, not just the place."),
        needed=(
            "Headcount by location · home-to-work distances and modes actually used · current "
            "allowance policy and uprating mechanism · salary bands and local-market pressure · "
            "rent and lease terms by site · remote/hybrid split · client location and travel "
            "requirements"),
        boundary=(
            "NO SALARIES, RENT, INTERNET OR SOFTWARE - the two largest costs of a service "
            "business are both absent, so nothing here is a statement about total cost. "
            "Published fares are averages for a journey, not any individual's commute, and we "
            "hold no distances or trip counts. The fare-versus-CPI comparison rests on only "
            "four usable months: 2026-02 is excluded because CPI year-on-year has a genuine "
            "hole there, and it is excluded rather than imputed."),
    ),
]


# ---------------------------------------------------------------------------
# Location wording. The metric is always named; "cheaper place to do business"
# is never used.
# ---------------------------------------------------------------------------
LOCATION_FRAMING = dict(
    question="How does the external cost environment differ between locations?",
    not_question="Where is the best location to run a business?",
    one_factor=(
        "Location is ONE of the things this project looks at. It is not the point of the "
        "project. A cheaper jurisdiction is not a better one, a dearer jurisdiction is not a "
        "worse one, and a dearer jurisdiction does not mean a business loses money there."),
    rule=(
        "Every comparison on this page names the COST BEING MEASURED. 'Lower measured diesel "
        "cost' is a statement about diesel and nothing else. Whether a business does well in "
        "a place also depends on revenue opportunity, customer demand, purchasing power, "
        "market size, competition, rent, wages, supplier access, infrastructure and how the "
        "company itself is set up. None of that is in this dataset."),
    stability=(
        "Where the order of jurisdictions keeps changing month to month, no jurisdiction is "
        "named as the cheapest or the dearest OVER TIME. The gap between the cheapest and the "
        "dearest is still shown, and each single month's ranking is still a valid snapshot; "
        "what is withheld is the lasting name. That applies to five of the nine costs: air, "
        "diesel, LPG 5 kg, LPG 12.5 kg and petrol."),
)


def build() -> dict[str, pd.DataFrame]:
    """Model tables for the explanation layer."""
    findings = pd.DataFrame([
        {"rank": f["rank"], "question": f["question"], "headline": f["headline"],
         "found": f["found"], "matters": f["matters"], "who": f["who"],
         "review": f["review"], "evidence": f["evidence"], "boundary": f["boundary"]}
        for f in FINDINGS])

    # Long form: one row per (finding, section), because a table is the only Power BI
    # visual that wraps a paragraph.
    sections = [("1. What we found", "found"), ("2. Why it matters", "matters"),
                ("3. Who should pay attention", "who"), ("4. What to review", "review"),
                ("5. Boundary - what this cannot prove", "boundary")]
    finding_rows = []
    for f in FINDINGS:
        for i, (heading, key) in enumerate(sections, start=1):
            finding_rows.append({"rank": f["rank"], "headline": f["headline"],
                                 "section_order": i, "section": heading, "body": f[key]})

    arch = pd.DataFrame([
        {"order": a["order"], "archetype": a["archetype"],
         "metric_codes": a["metric_codes"], "costs": a["costs"], "signals": a["signals"],
         "why": a["why"], "review": a["review"], "needed": a["needed"],
         "boundary": a["boundary"]}
        for a in ARCHETYPES])

    arch_sections = [("1. Which NBCI costs matter here", "costs"),
                     ("2. What the data currently shows", "signals"),
                     ("3. Why that could matter operationally", "why"),
                     ("4. What management should investigate internally", "review"),
                     ("5. Boundary - what this cannot tell you", "boundary"),
                     ("6. Company data needed before any decision", "needed")]
    arch_rows = []
    for a in ARCHETYPES:
        for i, (heading, key) in enumerate(arch_sections, start=1):
            arch_rows.append({"archetype": a["archetype"], "section_order": i,
                              "section": heading, "body": a[key]})

    equation = pd.DataFrame(
        [{"part_order": i, "part": p, "examples": e, "in_nbci": n}
         for i, (p, e, n) in enumerate(THE_EQUATION, start=1)])

    # The capability boundary as DATA. Held in one table with a direction column so a
    # single visual shows both halves side by side and neither half can quietly grow.
    cap_rows = []
    for i, s in enumerate(CAN_DO, start=1):
        cap_rows.append({"capability_order": i, "direction": "CAN do today",
                         "capability": s})
    for i, s in enumerate(CANNOT_DO, start=len(CAN_DO) + 1):
        cap_rows.append({"capability_order": i, "direction": "CANNOT do today",
                         "capability": s})

    return {
        "ref_finding": findings,
        "ref_finding_section": pd.DataFrame(finding_rows),
        "ref_archetype": arch,
        "ref_archetype_section": pd.DataFrame(arch_rows),
        "ref_scope": equation,
        "ref_capability": pd.DataFrame(cap_rows),
    }
