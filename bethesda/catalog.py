"""
Default test catalog loaded the first time the application starts.

Reference ranges are typical ADULT ranges used by many labs. Every lab must
validate these against its own analyser / reagent kit inserts and edit them in
the application (Tests -> Edit) before issuing real reports.

Parameter tuple format:
    (name, unit, low, high, low_female, high_female, ref_text, normal_value, options)
      - low/high       : numeric reference limits (None = no limit on that side)
      - low_female/... : female-specific limits (None = same as male/general)
      - ref_text       : extra text printed in the "Reference" column
      - normal_value   : for qualitative results (e.g. "Negative"); anything else is flagged
      - options        : suggested values for qualitative inputs, separated by "|"
"""


def P(name, unit="", low=None, high=None, low_f=None, high_f=None,
      text="", normal="", options=""):
    return (name, unit, low, high, low_f, high_f, text, normal, options)


NEG = "Negative|Positive"
NONREACT = "Non-Reactive|Reactive"
NIL = "Nil|Trace|+|++|+++|++++"

# (code, name, category, sample_type, price, fasting_required, [parameters])
TESTS = [
    # ------------------------------------------------------------ Haematology
    ("CBC", "Complete Blood Count (CBC)", "Haematology", "EDTA Whole Blood", 350, 0, [
        P("Haemoglobin", "g/dL", 13.0, 17.0, 12.0, 15.0),
        P("RBC Count", "million/µL", 4.5, 5.5, 3.8, 4.8),
        P("Packed Cell Volume (PCV)", "%", 40, 50, 36, 46),
        P("MCV", "fL", 83, 101),
        P("MCH", "pg", 27, 32),
        P("MCHC", "g/dL", 31.5, 34.5),
        P("RDW-CV", "%", 11.6, 14.0),
        P("Total WBC Count", "cells/µL", 4000, 11000),
        P("Neutrophils", "%", 40, 80),
        P("Lymphocytes", "%", 20, 40),
        P("Monocytes", "%", 2, 10),
        P("Eosinophils", "%", 1, 6),
        P("Basophils", "%", 0, 2),
        P("Platelet Count", "x10³/µL", 150, 410),
    ]),
    ("ESR", "Erythrocyte Sedimentation Rate (ESR)", "Haematology", "EDTA Whole Blood", 100, 0, [
        P("ESR (Westergren)", "mm/hr", 0, 15, 0, 20),
    ]),
    ("BGRP", "Blood Group & Rh Typing", "Haematology", "EDTA Whole Blood", 150, 0, [
        P("ABO Group", options="A|B|AB|O"),
        P("Rh (D) Type", options="Positive|Negative"),
    ]),
    ("RETIC", "Reticulocyte Count", "Haematology", "EDTA Whole Blood", 200, 0, [
        P("Reticulocyte Count", "%", 0.5, 2.5),
    ]),
    ("PS", "Peripheral Blood Smear", "Haematology", "EDTA Whole Blood", 250, 0, [
        P("RBC Morphology"), P("WBC Morphology"), P("Platelets"), P("Impression"),
    ]),
    ("MP", "Malaria Parasite Antigen (Rapid)", "Haematology", "EDTA Whole Blood", 400, 0, [
        P("P. falciparum Antigen", normal="Negative", options=NEG),
        P("P. vivax Antigen", normal="Negative", options=NEG),
    ]),

    # ------------------------------------------------------------ Coagulation
    ("PTINR", "Prothrombin Time (PT / INR)", "Coagulation", "Citrated Plasma", 350, 0, [
        P("Prothrombin Time", "seconds", 11.0, 13.5),
        P("Control", "seconds"),
        P("INR", "", 0.8, 1.1),
    ]),
    ("APTT", "Activated Partial Thromboplastin Time (aPTT)", "Coagulation", "Citrated Plasma", 450, 0, [
        P("aPTT", "seconds", 25, 35),
    ]),
    ("DDIMER", "D-Dimer", "Coagulation", "Citrated Plasma", 1200, 0, [
        P("D-Dimer", "ng/mL FEU", None, 500),
    ]),

    # ------------------------------------------------------------ Diabetes
    ("FBS", "Glucose - Fasting", "Diabetes", "Fluoride Plasma", 80, 1, [
        P("Fasting Plasma Glucose", "mg/dL", 70, 100, text="Prediabetes 100-125; Diabetes >= 126"),
    ]),
    ("PPBS", "Glucose - Post Prandial (2 hr)", "Diabetes", "Fluoride Plasma", 80, 0, [
        P("Post Prandial Glucose", "mg/dL", 70, 140, text="Diabetes >= 200"),
    ]),
    ("RBS", "Glucose - Random", "Diabetes", "Fluoride Plasma", 80, 0, [
        P("Random Plasma Glucose", "mg/dL", 70, 140),
    ]),
    ("HBA1C", "Glycated Haemoglobin (HbA1c)", "Diabetes", "EDTA Whole Blood", 500, 0, [
        P("HbA1c", "%", 4.0, 5.6, text="Prediabetes 5.7-6.4; Diabetes >= 6.5"),
        P("Estimated Average Glucose", "mg/dL", 68, 114),
    ]),
    ("INSF", "Insulin - Fasting", "Diabetes", "Serum", 800, 1, [
        P("Insulin (Fasting)", "µIU/mL", 2.6, 24.9),
    ]),

    # ------------------------------------------------------------ Biochemistry
    ("LIPID", "Lipid Profile", "Biochemistry", "Serum", 600, 1, [
        P("Total Cholesterol", "mg/dL", None, 200, text="Borderline 200-239; High >= 240"),
        P("Triglycerides", "mg/dL", None, 150, text="Borderline 150-199; High >= 200"),
        P("HDL Cholesterol", "mg/dL", 40, None, 50, None),
        P("LDL Cholesterol", "mg/dL", None, 100, text="Near optimal 100-129; High >= 160"),
        P("VLDL Cholesterol", "mg/dL", None, 30),
        P("Total Cholesterol / HDL Ratio", "", None, 5.0),
        P("LDL / HDL Ratio", "", None, 3.5),
    ]),
    ("LFT", "Liver Function Test (LFT)", "Biochemistry", "Serum", 700, 0, [
        P("Bilirubin - Total", "mg/dL", 0.3, 1.2),
        P("Bilirubin - Direct", "mg/dL", 0.0, 0.3),
        P("Bilirubin - Indirect", "mg/dL", 0.1, 1.0),
        P("SGOT / AST", "U/L", None, 40, None, 32),
        P("SGPT / ALT", "U/L", None, 41, None, 33),
        P("Alkaline Phosphatase (ALP)", "U/L", 40, 129, 35, 104),
        P("Gamma GT (GGT)", "U/L", 8, 61, 5, 36),
        P("Total Protein", "g/dL", 6.4, 8.3),
        P("Albumin", "g/dL", 3.5, 5.2),
        P("Globulin", "g/dL", 2.0, 3.5),
        P("A/G Ratio", "", 1.1, 2.2),
    ]),
    ("KFT", "Kidney Function Test (KFT / RFT)", "Biochemistry", "Serum", 700, 0, [
        P("Urea", "mg/dL", 17, 43),
        P("Blood Urea Nitrogen (BUN)", "mg/dL", 7, 20),
        P("Creatinine", "mg/dL", 0.7, 1.3, 0.6, 1.1),
        P("Uric Acid", "mg/dL", 3.5, 7.2, 2.6, 6.0),
        P("Sodium", "mmol/L", 136, 145),
        P("Potassium", "mmol/L", 3.5, 5.1),
        P("Chloride", "mmol/L", 98, 107),
        P("Calcium", "mg/dL", 8.6, 10.3),
        P("eGFR", "mL/min/1.73m²", 90, None),
    ]),
    ("ELEC", "Serum Electrolytes", "Biochemistry", "Serum", 400, 0, [
        P("Sodium", "mmol/L", 136, 145),
        P("Potassium", "mmol/L", 3.5, 5.1),
        P("Chloride", "mmol/L", 98, 107),
    ]),
    ("CREAT", "Creatinine", "Biochemistry", "Serum", 150, 0, [
        P("Creatinine", "mg/dL", 0.7, 1.3, 0.6, 1.1),
    ]),
    ("URIC", "Uric Acid", "Biochemistry", "Serum", 150, 0, [
        P("Uric Acid", "mg/dL", 3.5, 7.2, 2.6, 6.0),
    ]),
    ("CA", "Calcium", "Biochemistry", "Serum", 150, 0, [
        P("Calcium", "mg/dL", 8.6, 10.3),
    ]),
    ("MG", "Magnesium", "Biochemistry", "Serum", 300, 0, [
        P("Magnesium", "mg/dL", 1.7, 2.2),
    ]),
    ("PHOS", "Phosphorus", "Biochemistry", "Serum", 200, 0, [
        P("Phosphorus", "mg/dL", 2.5, 4.5),
    ]),
    ("AMYL", "Amylase", "Biochemistry", "Serum", 450, 0, [
        P("Amylase", "U/L", 28, 100),
    ]),
    ("LIPASE", "Lipase", "Biochemistry", "Serum", 600, 0, [
        P("Lipase", "U/L", 13, 60),
    ]),
    ("IRON", "Iron Studies", "Biochemistry", "Serum", 900, 1, [
        P("Serum Iron", "µg/dL", 65, 175, 50, 170),
        P("TIBC", "µg/dL", 250, 450),
        P("Transferrin Saturation", "%", 20, 50),
        P("Ferritin", "ng/mL", 30, 400, 13, 150),
    ]),
    ("VITD", "Vitamin D (25-OH)", "Biochemistry", "Serum", 1400, 0, [
        P("25-OH Vitamin D", "ng/mL", 30, 100, text="Deficient < 20; Insufficient 20-29"),
    ]),
    ("VITB12", "Vitamin B12", "Biochemistry", "Serum", 1000, 0, [
        P("Vitamin B12", "pg/mL", 211, 911),
    ]),
    ("FOLATE", "Folic Acid", "Biochemistry", "Serum", 900, 0, [
        P("Folate", "ng/mL", 3.9, 26.8),
    ]),

    # ------------------------------------------------------------ Cardiac
    ("TROPI", "Troponin I", "Cardiac", "Serum", 1000, 0, [
        P("Troponin I", "ng/mL", None, 0.04),
    ]),
    ("CKMB", "CK-MB", "Cardiac", "Serum", 600, 0, [
        P("CK-MB", "U/L", None, 24),
    ]),
    ("HSCRP", "hs-CRP (High Sensitivity C-Reactive Protein)", "Cardiac", "Serum", 700, 0, [
        P("hs-CRP", "mg/L", None, 1.0, text="Avg risk 1-3; High risk > 3"),
    ]),

    # ------------------------------------------------------------ Hormones
    ("T3T4TSH", "Thyroid Profile (T3, T4, TSH)", "Hormones", "Serum", 500, 0, [
        P("Total T3", "ng/dL", 80, 200),
        P("Total T4", "µg/dL", 5.1, 14.1),
        P("TSH", "µIU/mL", 0.27, 4.2),
    ]),
    ("FTFT", "Free Thyroid Profile (FT3, FT4, TSH)", "Hormones", "Serum", 700, 0, [
        P("Free T3", "pg/mL", 2.0, 4.4),
        P("Free T4", "ng/dL", 0.93, 1.7),
        P("TSH", "µIU/mL", 0.27, 4.2),
    ]),
    ("TSH", "TSH (Ultrasensitive)", "Hormones", "Serum", 300, 0, [
        P("TSH", "µIU/mL", 0.27, 4.2),
    ]),
    ("PRL", "Prolactin", "Hormones", "Serum", 600, 0, [
        P("Prolactin", "ng/mL", 4.0, 15.2, 4.8, 23.3),
    ]),
    ("LH", "Luteinising Hormone (LH)", "Hormones", "Serum", 550, 0, [
        P("LH", "mIU/mL", text="Male 1.7-8.6; Female: Follicular 2.4-12.6, Mid-cycle 14-96, Luteal 1-11.4, Post-menopause 7.7-58.5"),
    ]),
    ("FSH", "Follicle Stimulating Hormone (FSH)", "Hormones", "Serum", 550, 0, [
        P("FSH", "mIU/mL", text="Male 1.5-12.4; Female: Follicular 3.5-12.5, Mid-cycle 4.7-21.5, Luteal 1.7-7.7, Post-menopause 25.8-134.8"),
    ]),
    ("TESTO", "Testosterone - Total", "Hormones", "Serum", 800, 0, [
        P("Testosterone (Total)", "ng/dL", 249, 836, 8, 48),
    ]),
    ("CORT", "Cortisol (Morning)", "Hormones", "Serum", 700, 0, [
        P("Cortisol (8-10 AM)", "µg/dL", 6.2, 19.4),
    ]),
    ("BHCG", "Beta hCG (Quantitative)", "Hormones", "Serum", 700, 0, [
        P("Beta hCG", "mIU/mL", None, 5, text="Non-pregnant < 5; Pregnancy > 25"),
    ]),
    ("PSA", "PSA - Total (Prostate Specific Antigen)", "Hormones", "Serum", 800, 0, [
        P("PSA (Total)", "ng/mL", None, 4.0),
    ]),

    # ------------------------------------------------------------ Immunology / Serology
    ("CRP", "C-Reactive Protein (CRP)", "Immunology", "Serum", 400, 0, [
        P("CRP", "mg/L", None, 5.0),
    ]),
    ("RAF", "Rheumatoid Factor (RA)", "Immunology", "Serum", 450, 0, [
        P("RA Factor", "IU/mL", None, 14),
    ]),
    ("ASO", "Anti Streptolysin O (ASO)", "Immunology", "Serum", 500, 0, [
        P("ASO Titre", "IU/mL", None, 200),
    ]),
    ("WIDAL", "Widal Test (Slide)", "Immunology", "Serum", 200, 0, [
        P("S. Typhi 'O'", text="< 1:80", options="< 1:20|1:40|1:80|1:160|1:320"),
        P("S. Typhi 'H'", text="< 1:160", options="< 1:20|1:40|1:80|1:160|1:320"),
        P("S. Paratyphi 'AH'", text="< 1:160", options="< 1:20|1:40|1:80|1:160|1:320"),
        P("S. Paratyphi 'BH'", text="< 1:160", options="< 1:20|1:40|1:80|1:160|1:320"),
    ]),
    ("TYPHIDOT", "Typhoid IgM (Rapid)", "Immunology", "Serum", 600, 0, [
        P("S. Typhi IgM", normal="Negative", options=NEG),
    ]),
    ("DENGNS1", "Dengue NS1 Antigen", "Immunology", "Serum", 600, 0, [
        P("Dengue NS1 Antigen", normal="Negative", options=NEG),
    ]),
    ("DENGAB", "Dengue IgG / IgM Antibodies", "Immunology", "Serum", 800, 0, [
        P("Dengue IgM", normal="Negative", options=NEG),
        P("Dengue IgG", normal="Negative", options=NEG),
    ]),
    ("HIV", "HIV I & II Antibodies", "Immunology", "Serum", 400, 0, [
        P("HIV I & II", normal="Non-Reactive", options=NONREACT),
    ]),
    ("HBSAG", "Hepatitis B Surface Antigen (HBsAg)", "Immunology", "Serum", 350, 0, [
        P("HBsAg", normal="Non-Reactive", options=NONREACT),
    ]),
    ("HCV", "Hepatitis C Antibody (Anti-HCV)", "Immunology", "Serum", 600, 0, [
        P("Anti-HCV", normal="Non-Reactive", options=NONREACT),
    ]),
    ("VDRL", "VDRL / RPR (Syphilis)", "Immunology", "Serum", 250, 0, [
        P("VDRL", normal="Non-Reactive", options=NONREACT),
    ]),

    # ------------------------------------------------------------ Clinical Pathology
    ("URINE", "Urine Routine & Microscopy", "Clinical Pathology", "Urine", 150, 0, [
        P("Colour", text="Pale Yellow", options="Pale Yellow|Yellow|Dark Yellow|Amber|Red|Colourless"),
        P("Appearance", normal="Clear", options="Clear|Slightly Turbid|Turbid"),
        P("pH", "", 4.5, 8.0),
        P("Specific Gravity", "", 1.005, 1.030),
        P("Protein", normal="Nil", options=NIL),
        P("Glucose", normal="Nil", options=NIL),
        P("Ketone Bodies", normal="Negative", options=NEG),
        P("Blood", normal="Negative", options=NEG),
        P("Pus Cells", "/hpf", text="0-5"),
        P("RBCs", "/hpf", text="0-2"),
        P("Epithelial Cells", "/hpf", text="0-5"),
        P("Casts", normal="Nil", options="Nil|Present"),
        P("Crystals", normal="Nil", options="Nil|Present"),
    ]),
    ("UPT", "Urine Pregnancy Test", "Clinical Pathology", "Urine", 150, 0, [
        P("Urine hCG", options=NEG),
    ]),
    ("STOOL", "Stool Routine", "Clinical Pathology", "Stool", 200, 0, [
        P("Consistency", options="Formed|Semi-formed|Loose|Watery"),
        P("Occult Blood", normal="Negative", options=NEG),
        P("Ova / Cysts", normal="Not Seen", options="Not Seen|Seen"),
        P("Pus Cells", "/hpf", text="0-2"),
    ]),
]

# Ready-made packages: (code, name, price, [test codes])
PACKAGES = [
    ("PKG-BASIC", "Basic Health Checkup", 1499, ["CBC", "FBS", "LIPID", "LFT", "KFT", "URINE"]),
    ("PKG-DIAB", "Diabetes Care Panel", 1199, ["FBS", "PPBS", "HBA1C", "KFT", "URINE"]),
    ("PKG-FULL", "Full Body Checkup", 3499, ["CBC", "ESR", "FBS", "HBA1C", "LIPID", "LFT", "KFT",
                                            "T3T4TSH", "VITD", "VITB12", "IRON", "URINE"]),
    ("PKG-FEVER", "Fever Panel", 1299, ["CBC", "ESR", "MP", "WIDAL", "DENGNS1", "URINE", "CRP"]),
]
