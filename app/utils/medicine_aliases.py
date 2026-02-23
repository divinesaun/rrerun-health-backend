"""
Medicine alias mapping for search expansion.

When a user searches for a medicine, we expand the query to include all known
aliases (brand names, generic names, regional names) so that "panado" also
matches "paracetamol", "tylenol", etc.

To add new aliases, simply add entries to ALIAS_MAP below.
No database migration required.
"""

from typing import List

# generic_name → [brand1, brand2, ...]
# All keys and values are lowercase for matching.
ALIAS_MAP: dict[str, list[str]] = {
    # Pain / Fever
    "paracetamol": ["panado", "tylenol", "acetaminophen", "calpol", "panadol", "doliprane", "efferalgan"],
    "ibuprofen": ["brufen", "advil", "nurofen", "motrin", "ibupain"],
    "aspirin": ["disprin", "ecotrin", "bayer aspirin", "acetylsalicylic acid"],
    "diclofenac": ["voltaren", "cataflam", "voltarol", "diclac"],
    "naproxen": ["naprosyn", "aleve", "naprogesic"],
    "tramadol": ["tramal", "ultram", "zydol"],
    "codeine": ["codeine phosphate", "solpadeine"],

    # Antibiotics
    "amoxicillin": ["amoxil", "augmentin", "clavamox", "moxatag"],
    "azithromycin": ["zithromax", "azithral", "zmax"],
    "ciprofloxacin": ["cipro", "ciproxin", "ciloxan"],
    "metronidazole": ["flagyl", "metrogyl", "rozex"],
    "doxycycline": ["vibramycin", "doryx", "monodox"],
    "flucloxacillin": ["floxapen", "fluclox"],
    "erythromycin": ["erythrocin", "eryc", "ery-tab"],
    "cephalexin": ["keflex", "cefalexin"],
    "cotrimoxazole": ["bactrim", "septrin", "co-trimoxazole", "trimethoprim-sulfamethoxazole"],

    # Stomach / GI
    "omeprazole": ["losec", "prilosec", "nexium", "esomeprazole"],
    "ranitidine": ["zantac", "rantec"],
    "loperamide": ["imodium", "lomotil"],
    "buscopan": ["hyoscine", "scopolamine butylbromide"],
    "metoclopramide": ["maxolon", "plasil", "reglan"],
    "domperidone": ["motilium", "vomistop"],

    # Allergy / Antihistamines
    "cetirizine": ["zyrtec", "allertec", "reactine"],
    "loratadine": ["claritin", "clarityn", "lorano"],
    "chlorphenamine": ["chlorpheniramine", "piriton", "chlor-trimeton"],
    "fexofenadine": ["allegra", "telfast"],

    # Blood Pressure / Heart
    "amlodipine": ["norvasc", "amlopress"],
    "atenolol": ["tenormin", "atenol"],
    "losartan": ["cozaar", "losartic"],
    "enalapril": ["renitec", "vasotec"],
    "hydrochlorothiazide": ["hctz", "esidrix", "microzide"],
    "nifedipine": ["adalat", "procardia"],
    "simvastatin": ["zocor", "simvacor"],
    "atorvastatin": ["lipitor", "atorva"],

    # Diabetes
    "metformin": ["glucophage", "glycomet", "fortamet"],
    "glibenclamide": ["daonil", "glyburide"],
    "glimepiride": ["amaryl", "glimep"],
    "insulin": ["humulin", "novorapid", "lantus", "actrapid"],

    # Respiratory
    "salbutamol": ["ventolin", "airomir", "albuterol", "proventil"],
    "bromhexine": ["bisolvon", "bromhex"],
    "fluticasone": ["flixotide", "flovent"],
    "montelukast": ["singulair", "montek"],
    "prednisolone": ["prelone", "deltacortril"],

    # Skin
    "hydrocortisone": ["cortaid", "locoid"],
    "clotrimazole": ["canesten", "lotriderm"],
    "fluconazole": ["diflucan", "flucazole"],
    "acyclovir": ["zovirax", "aciclovir"],
    "mupirocin": ["bactroban", "mupiderm"],

    # Vitamins / Supplements
    "vitamin c": ["ascorbic acid", "cevitamic acid", "redoxon"],
    "vitamin b complex": ["b-complex", "neurobion"],
    "iron supplement": ["ferrous sulfate", "ferrous gluconate", "fefol"],
    "zinc": ["zinc sulfate", "zinc gluconate"],
    "folic acid": ["folate", "vitamin b9"],
    "calcium": ["calcium carbonate", "caltrate", "oscal"],

    # Other common
    "oral rehydration salts": ["ors", "ors sachets", "dioralyte"],
    "cough syrup": ["benylin", "robitussin", "pholcodine"],
    "antacid": ["gaviscon", "mylanta", "rennie", "tums"],
}

# Build a reverse lookup: alias → generic_name
_REVERSE_MAP: dict[str, str] = {}
for _generic, _aliases in ALIAS_MAP.items():
    _REVERSE_MAP[_generic] = _generic  # generic maps to itself
    for _alias in _aliases:
        _REVERSE_MAP[_alias.lower()] = _generic


def expand_search_terms(query: str) -> List[str]:
    """Given a medicine name/alias, return all equivalent names to search for.

    Returns a list including the original query plus all aliases.
    Example: expand_search_terms("panado") → ["panado", "paracetamol", "tylenol", ...]
    """
    normalized = query.strip().lower()
    # Check if query matches a generic name
    if normalized in ALIAS_MAP:
        return [normalized] + ALIAS_MAP[normalized]
    # Check if query matches an alias
    generic = _REVERSE_MAP.get(normalized)
    if generic:
        return [normalized, generic] + [a for a in ALIAS_MAP[generic] if a != normalized]
    # No alias found — return as-is
    return [normalized]
