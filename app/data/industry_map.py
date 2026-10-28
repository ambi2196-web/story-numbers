"""Map Yahoo Finance industries and countries onto Damodaran's industry groups and regions."""
import difflib

from app.data.damodaran import industries

# Yahoo Finance industry -> Damodaran industry. Anything missing falls back to the closest name match.
YAHOO_TO_DAMODARAN = {
    "Auto Manufacturers": "Auto & Truck",
    "Auto Parts": "Auto Parts",
    "Auto & Truck Dealerships": "Retail (Automotive)",
    "Farm & Heavy Construction Machinery": "Machinery",
    "Specialty Industrial Machinery": "Machinery",
    "Recreational Vehicles": "Recreation",
    "Banks - Regional": "Banks (Regional)",
    "Banks - Diversified": "Bank (Money Center)",
    "Credit Services": "Financial Svcs. (Non-bank & Insurance)",
    "Capital Markets": "Brokerage & Investment Banking",
    "Asset Management": "Investments & Asset Management",
    "Insurance - Life": "Insurance (Life)",
    "Insurance - Property & Casualty": "Insurance (Prop/Cas.)",
    "Insurance - Diversified": "Insurance (General)",
    "Software - Application": "Software (System & Application)",
    "Software - Infrastructure": "Software (System & Application)",
    "Information Technology Services": "Computer Services",
    "Internet Content & Information": "Software (Internet)",
    "Internet Retail": "Retail (Special Lines)",
    "Electronic Gaming & Multimedia": "Software (Entertainment)",
    "Consumer Electronics": "Electronics (Consumer & Office)",
    "Computer Hardware": "Computers/Peripherals",
    "Semiconductors": "Semiconductor",
    "Semiconductor Equipment & Materials": "Semiconductor Equip",
    "Communication Equipment": "Telecom. Equipment",
    "Telecom Services": "Telecom. Services",
    "Drug Manufacturers - General": "Drugs (Pharmaceutical)",
    "Drug Manufacturers - Specialty & Generic": "Drugs (Pharmaceutical)",
    "Biotechnology": "Drugs (Biotechnology)",
    "Medical Devices": "Healthcare Products",
    "Medical Instruments & Supplies": "Healthcare Products",
    "Medical Care Facilities": "Hospitals/Healthcare Facilities",
    "Diagnostics & Research": "Healthcare Support Services",
    "Health Information Services": "Heathcare Information and Technology",
    "Oil & Gas Integrated": "Oil/Gas (Integrated)",
    "Oil & Gas E&P": "Oil/Gas (Production and Exploration)",
    "Oil & Gas Refining & Marketing": "Oil/Gas Distribution",
    "Oil & Gas Midstream": "Oil/Gas Distribution",
    "Oil & Gas Equipment & Services": "Oilfield Svcs/Equip.",
    "Utilities - Regulated Electric": "Utility (General)",
    "Utilities - Independent Power Producers": "Power",
    "Utilities - Renewable": "Green & Renewable Energy",
    "Utilities - Regulated Gas": "Utility (General)",
    "Utilities - Regulated Water": "Utility (Water)",
    "Utilities - Diversified": "Utility (General)",
    "Steel": "Steel",
    "Aluminum": "Metals & Mining",
    "Copper": "Metals & Mining",
    "Other Industrial Metals & Mining": "Metals & Mining",
    "Gold": "Precious Metals",
    "Thermal Coal": "Coal & Related Energy",
    "Building Materials": "Building Materials",
    "Building Products & Equipment": "Building Materials",
    "Engineering & Construction": "Engineering/Construction",
    "Residential Construction": "Homebuilding",
    "Real Estate - Development": "Real Estate (Development)",
    "Real Estate - Diversified": "Real Estate (General/Diversified)",
    "Real Estate Services": "Real Estate (Operations & Services)",
    "Specialty Chemicals": "Chemical (Specialty)",
    "Chemicals": "Chemical (Basic)",
    "Agricultural Inputs": "Chemical (Diversified)",
    "Packaged Foods": "Food Processing",
    "Confectioners": "Food Processing",
    "Food Distribution": "Food Wholesalers",
    "Grocery Stores": "Retail (Grocery and Food)",
    "Beverages - Non-Alcoholic": "Beverage (Soft)",
    "Beverages - Brewers": "Beverage (Alcoholic)",
    "Beverages - Wineries & Distilleries": "Beverage (Alcoholic)",
    "Tobacco": "Tobacco",
    "Household & Personal Products": "Household Products",
    "Apparel Manufacturing": "Apparel",
    "Apparel Retail": "Retail (Special Lines)",
    "Textile Manufacturing": "Apparel",
    "Footwear & Accessories": "Shoe",
    "Luxury Goods": "Retail (Special Lines)",
    "Department Stores": "Retail (General)",
    "Discount Stores": "Retail (General)",
    "Specialty Retail": "Retail (Special Lines)",
    "Home Improvement Retail": "Retail (Building Supply)",
    "Furnishings, Fixtures & Appliances": "Furn/Home Furnishings",
    "Restaurants": "Restaurant/Dining",
    "Lodging": "Hotel/Gaming",
    "Resorts & Casinos": "Hotel/Gaming",
    "Gambling": "Hotel/Gaming",
    "Travel Services": "Business & Consumer Services",
    "Leisure": "Recreation",
    "Entertainment": "Entertainment",
    "Broadcasting": "Broadcasting",
    "Publishing": "Publishing & Newspapers",
    "Advertising Agencies": "Advertising",
    "Airlines": "Air Transport",
    "Airports & Air Services": "Air Transport",
    "Railroads": "Transportation (Railroads)",
    "Trucking": "Trucking",
    "Marine Shipping": "Shipbuilding & Marine",
    "Integrated Freight & Logistics": "Transportation",
    "Aerospace & Defense": "Aerospace/Defense",
    "Electrical Equipment & Parts": "Electrical Equipment",
    "Electronic Components": "Electronics (General)",
    "Conglomerates": "Diversified",
    "Education & Training Services": "Education",
    "Packaging & Containers": "Packaging & Container",
    "Paper & Paper Products": "Paper/Forest Products",
    "Waste Management": "Environmental & Waste Services",
    "Staffing & Employment Services": "Business & Consumer Services",
    "Specialty Business Services": "Business & Consumer Services",
    "Personal Services": "Business & Consumer Services",
    "Rental & Leasing Services": "Business & Consumer Services",
    "Solar": "Green & Renewable Energy",
}

COUNTRY_TO_REGION = {"India": "India", "United States": "US", "China": "China", "Hong Kong": "China", "Japan": "Japan"}
EUROPE = {"United Kingdom", "Germany", "France", "Netherlands", "Switzerland", "Sweden", "Spain", "Italy", "Ireland",
          "Denmark", "Norway", "Finland", "Belgium", "Austria", "Portugal", "Luxembourg", "Poland", "Greece"}
EMERGING = {"Brazil", "Mexico", "Indonesia", "South Africa", "Turkey", "Thailand", "Malaysia", "Philippines",
            "Vietnam", "Chile", "Colombia", "Peru", "Saudi Arabia", "United Arab Emirates", "Egypt", "Nigeria",
            "Taiwan", "South Korea", "Argentina", "Pakistan", "Bangladesh", "Sri Lanka", "Qatar", "Kenya"}


def to_damodaran_industry(yahoo_industry: str | None, region: str = "Global") -> str:
    if yahoo_industry in YAHOO_TO_DAMODARAN:
        return YAHOO_TO_DAMODARAN[yahoo_industry]
    names = [n for n in industries(region) if not n.startswith("Total Market")]
    match = difflib.get_close_matches(yahoo_industry or "", names, n=1, cutoff=0.4)
    return match[0] if match else "Total Market (without financials)"


def to_region(country: str | None) -> str:
    if country in COUNTRY_TO_REGION:
        return COUNTRY_TO_REGION[country]
    if country in EUROPE:
        return "Europe"
    if country in EMERGING:
        return "Emerging"
    return "Global"
