"""
Single source of truth for the de-identification A/B test catalog.

14 realistic Indian hospital notes (3 synthetic + 11 field) with
per-note PII/clinical token lists and the date list, plus the shared
scoring and span-propagation utilities. Importable without Django
or Ollama.
"""
import re


DOC_CLINICAL = """DISCHARGE SUMMARY
KOLKATA MEDICAL INSTITUTE, Salt Lake, Kolkata - 700091

Patient: Mr. Rajesh Kumar S/o Late Bhaskar Kumar, Age 56 years, Sex: Male
Address: House No. 12/4B, Ghat Road, Village Patia, P.O. Mahishadal,
District West Medinipur, West Bengal - 716130
MR/26/092837  |  Mobile: +91 98312 45678  |  Aadhaar: 8412 3456 7890
Date of Admission: 01/02/2024    Date of Discharge: 06/02/2024

HISTORY OF PRESENTING COMPLAINTS:
The patient presented with progressive swelling in the left breast for 1
month, with skin dimpling noticed for 2 weeks. He had a fever for 3 days
prior to admission. Family history: mother died of breast cancer.

EXAMINATION:
Left breast lump 4 x 3.5 cm, hard, with skin tethering. Left axillary
lymph nodes: 3 matted nodes, largest 12 mm.

INVESTIGATIONS:
CEA 4.2 ng/mL, CA 15-3 380 IU/mL. FNAC: malignant cells.
Mammogram: EIBC. MRN: MR/26/092837

DIAGNOSIS: Left breast carcinoma
TREATMENT: Neoadjuvant chemotherapy (EC-T) for 4 cycles.
FOLLOW UP: advised in 1 month with CEA and mammogram.

Referring doctor: Dr. Meena Nair, Oncologist, Apollo Hospital, Kolkata.
Attending physician: Dr. Subhojit Das
"""

DOC_RADIOLOGY = """RADIOLOGY REPORT
KOLKATA MEDICAL INSTITUTE - Department of Diagnostic Radiology
Report No: RAD/26/004512
Patient: Rajesh Kumar            MRN: MR/26/092837
DOB: 12/04/1968                  Date of Exam: 04/02/2024
Referring Physician: Dr. Meena Nair

CLINICAL HISTORY: Carcinoma left breast on neoadjuvant chemotherapy.
Staging CT requested.

CT CHEST / ABDOMEN / PELVIS WITH CONTRAST
Technologist: Mr. Prasant Roy

FINDINGS:
Lungs: No pulmonary metastasis. Right upper lobe: 3 mm nonspecific nodule.
Lymph nodes: Subcarinal node 9 mm (short axis) - borderline.
Liver: No focal lesion. No ascites. Spleen normal.
Pelvis: No pelvic sidewall lymphadenopathy.

IMPRESSION:
No distant metastasis on CT chest, abdomen and pelvis.
Staging: cT2 N1 M0.
Repeat CT advised in 3 months.

Reported by: Dr. Anirban Ghosh, Senior Radiologist
Verified by: Dr. S. K. Bose, Consultant Radiologist
"""

DOC_PATHOLOGY = """HISTOPATHOLOGY REPORT
KOLKATA MEDICAL INSTITUTE - Department of Pathology
Accession No: HP/26/011111
Specimen: Left breast lump biopsy
Patient: Rajesh Kumar
MRN: MR/26/092837
Date of Reception: 02/02/2024    Date of Reporting: 05/02/2024
Referring: Dr. Subhojit Das

CLINICAL: Left breast lump 4 x 3.5 cm with skin involvement.

GROSS: Grey-white firm tissue 2.5 x 2 x 1.8 cm.
MICROSCOPY: Infiltrating ductal carcinoma, Grade III (Nottingham 8/9).
Lymphovascular invasion: present in 3 vessels per high power field.
Margins: closest margin 1.2 mm (inferior).
IMMUNOHISTOCHEMISTRY: ER negative, PR negative, HER2 3+ (overexpressed),
Ki-67 45%. p16 shows patchy nuclear expression. D2-40 highlights LVI.
Lymph nodes examined: 2/12 positive (left axillary).

DIAGNOSIS: Invasive ductal carcinoma, triple-positive, Grade III.
IHC: HER2 positive - suitable for targeted therapy.

Reported by: Dr. Ritu Mandal, Consultant Pathologist
"""

DOCS_CLEAN = [
    ('AB-SYNTH clinical note (discharge summary)', DOC_CLINICAL, '.csv'),
    ('AB-SYNTH radiology report (CT staging)', DOC_RADIOLOGY, '.csv'),
    ('AB-SYNTH pathology report (histopathology)', DOC_PATHOLOGY, '.csv'),
]

# ---------------------------------------------------------------------------
# Realistic field notes (provided by the team): sparse scattered
# identifiers, inconsistent date formats/separators, misspellings,
# abbreviations, initial-only names, name variants across records,
# date-like clinical values (fractions, titers, BP, times).
# ---------------------------------------------------------------------------

DOC_CARDIOL = """Smt Kamla Devi    61/F    W/o Ramlal Verma
Village Sonpur, Dist Saran (Bihar)

1.2.24 
c/o breathlessness x 10 days, B/L pedal oedema, orthopnoea since 3-4 days. 
H/o HTN since 2015, on Tab Amlodipine 5mg OD (irregular). no h/o DM. 
Attendant (son) says pt not taking salt restriction.

O/E: BP 150/94, P 102 irreg, SpO2 90% RA
JVP raised. B/L basal crepts. 
Echo - EF 35%, mild MR. (Echo done by Anita Kumari, tech)
Dx: ? CCF / r/o DCM

Rx: Inj Lasix 40mg IV BD x 3 days
Fluid restrict 1.5 L/day
Tab Ecosprin 75 OD

Day 2 (2/2): Kamala Devi feeling better, less breathless. 
Today BP 140/90, SpO2 94% RA
Wt yesterday 58 kg, today 56.5 kg
Husband Ram Lal Verma wants discharge, counselled.

Plan: shift to oral diuretics, review in OPD after 10 d with ECG + RFT 

Dr Suresh Pathek, DM Cardiology
(Dr. Neha Gupta, DM Resident) 
"""

DOC_ORTHO = """DISCHARGE SUMMARY
Pt: Mr. Arvind Subramaniam, 91 y/M       MRN not on sheet (see file cover)
DOA: 28 Jan 24    DOD: 1st Feb 24

H/o fall at home 3 days PTA, c/o pain R hip. 
Lives w/ son in Tambaram, Chennai. ph 98410 22xxx
X-ray - # neck of femur R. 
Pre-op: Hb 9.8, creat 1.4, ECG - AF. 
DHFR done 30/1/24 (R hemiarthroplasty). Dr Venkat Raman, Ortho
Post-op day 2 pt mobilised w/ walker. 
Inj Enoxaparin 40mg SC OD x 14 days; Tab Tramadol 50 mg BD x 5 d (10 tabs)
Wound check "yesterday" - clean. Sutures out after 2 wks (~ mid Feb)
Prev. admission here in Oct 2023 for UTI. 

Physio: Mr. Joseph T. 
Next review 12/2 with Dr. Raman.

Discharge prepared by: Dr. Lakshmi N (PG)
"""

DOC_MED = """Name: Rajesh Kumar  S/o Late Hari Prasad       M/52
Ward 4, bed 12

Admitted 1/2/24 c/o fever x 5 days, chills, headache. 
febrile since 3/20 per attendant (?? 3/2 - clarified later, wife says 28/1)
No h/o cough, loose motions. No h/o DM/HTN. 
Pt is a truck driver, resides Rampur Khas, Dist. Sitapur UP

On exam: T 102F, P 104, BP 110/70
Widal +ve (O 1:160). Malaria Ag neg. 
Dx: Enteric fever, r/o dengue

Rx:
IV paracetamol 1g 8 hourly
Inj Ceftriaxone 2g IV OD x 7 days
ORS
Tab Pantop 40 OD  (12 tabs given on discharge)

Day 3: Rajes Kumar afebrile since yesterday. tolerating oral. 
Platelets 1.2 lakh -> 1.8 lakh on 5/2
Lab tech - Sunil Chauhan (sample coll.)
Discharge planned 02-24 end if stable. 
Review OPD after 1 wk. wife (Meena) will bring pt.

Dr Priya Nair, Sr Resident 
(Dr. S. Banerjee, Prof. Medicine)
"""

DOC_SURG = """Smt Sunita Devi            F/46
Dr. Mehra's unit, SSMCH        

1 Feb 24
c/o swelling L breast since 1 mnth, painless. no nipple discharge. 
H/O wt loss ~4 kg in 2 mnths. no h/o trauma. 
LMP 20/1. mother had ca breast (d. 2019)
Vill - Bhagwanpur, Dist Vaishali, Bihar
ph 94310-55xxx (husband)

O/E: Pt afebrile, BP 130/84, P 88/min
L breast - 4x3 cm lump UOQ, hard, fixed. Axillary LN palpable L
P/A - soft, no organomegaly

Dx: Ca L breast ? T3N1
Plan: Core biopsy + USG abd + CXR. Admit 1/2/24 for work up.

2/2 - USG done by tech Ramesh Yadav. liver - ? 2 focal lesions, R/o metatasis
FNAC axillary node - reactive lymph? await rpt
3-2-24 biopsy report: IDC grade II, ER+ PR+ Her2 neg. 2/12 nodes +ve on SLNB (path rpt 14.02.24)

Tab Letrozole 2.5mg OD x 30 tabs
Inj Zoledronic acid 4mg IV
F/U after 2 wks with reports, "recption" counter 3

                                      Dr A. K. Mehra
                                      MS, Gen Surg
"""

DOC_TATA = """TATA MEDICAL CENTRE, KOLKATA  
Surgical Oncology OPD

Mrs. Ananya Mukherjee  
Seen on: 01-02-2024

c/o swelling L breast since 1 mnth, painless initially. No nipple discharge. H/O HTN x 4 yrs. No h/o DM. Menopause attained 2020. Family h/o malignancy neg.

Examination: 4 x 3 cm lump in upper outer quadrant L breast, hard, irregular, poorly mobile. Few L axillary nodes palpable.

USG breast dated 1/2/24: BIRADS 5 lesion L breast with suspicious axillary lymph nodes.

Core biopsy \u2013 01 Feb 2024: Invasive breast carcinoma NST, Grade II, ER positive, PR positive, HER2 negative, Ki-67 25%.

Plan: CECT thorax/abdomen, bone scan, CBC, LFT, RFT. Review with reports.

Dr. S. Banerjee, Consultant, Surgical Oncology

---

IP admission note \u2013 02-02-2024

Patient name: Ananya Mukherjee  
Address: Vill. Boral, PO Garia, South 24 Parganas

Admitted for staging workup and treatment planning. Pt clinically stable. BP 130/80 mmHg, pulse 82/min, afebrile.

CT report 02.02.2024: No definite distant metatasis. Left axillary lymphadenopathy.

Histopathology report mentions Ananya Mukherjee; one nursing entry on 2/2/24 records the name as Ananya Mukherji.

Treatment discussed with patient and family. MDT opinion awaited.
"""

DOC_NADIA = """DISTRICT HOSPITAL, NADIA  
Emergency / Medicine Department

Name: Rajesh Kumar  
Age/Sex: 56/M  
Address: Krishnanagar, Nadia  
Date of admission: 1/2/24

Pt brought with fever, cough and breathlessness since 3 days. Febrile since 3/20 (as written in referral slip; exact start date unclear). H/O COPD. No known drug allergy.

On examination: conscious, oriented. Temp 101.4 F, PR 108/min, BP 100/64 mmHg, SpO2 91% on room air. P/A soft, non-tender. Bilateral crepts present.

Provisional dx: LRTI ? pneumonia. R/o sepsis.

Investigations 01 Feb 2024:
Hb 10.8 g/dL, TLC 15,600/cumm, platelets 1.8 lakh/cumm, creatinine 1.2 mg/dL. Chest X-ray shows R lower zone opacity.

Treatment started:
IV ceftriaxone 1 g 12 hourly.
IV paracetamol 1 g 8 hourly if fever.
Nebulisation with salbutamol + ipratropium 8 hourly.
Oxygen by nasal prongs 2 L/min.

Progress note \u2013 02-02-2024

Fever reduced. SpO2 95% on oxygen. Oral intake adequate. Continue antibiotics.

Medication reconciliation: Patient reports taking 12 tabs of paracetamol-containing OTC medication over approximately 2 days before admission; exact strength and timing uncertain. Informed treating physician. Toxicology assessment advised as clinically indicated.

Technician: S. Mondal, Lab Collection, recorded sample receipt at 07:45 on 02/02/2024.

Dr A. Ghosh  
Duty Medical Officer
"""

DOC_RT = """RADIATION ONCOLOGY \u2013 NEW PATIENT  
Patient: Smt. Sunita Devi  
Age: 48 yrs / F  
Village: Barhampur, Murshidabad

Registration date 01.02.2024

c/o foul smelling vaginal discharge and intermittent bleeding per vaginum x 4 mnths. H/O weight loss approx 5 kg in 3 months. Menopause not attained.

Gynae exam: Cervix enlarged, friable growth involving both lips, bleeds on touch. Parametrium thickened bilaterally, more on L. Clinical impression: carcinoma cervix, locally advanced.

Biopsy (01 Feb 2024): Squamous cell carcinoma, moderately differentiated.

MRI pelvis 1/2: Cervical mass 5.2 x 4.8 x 4.5 cm with bilateral parametrial invasion. No definite pelvic sidewall involvement. Suspicious L external iliac node.

Dx: Ca cervix, FIGO stage IIIB (clinical; correlate with complete staging).

Plan: Definitive concurrent chemoradiotherapy. EBRT 45 Gy in 25 fractions to pelvis with weekly cisplatin as tolerated, followed by assessment for brachytherapy. Counselling completed with patient and son.

Review entry: 02-24
Pt came with CBC and RFT. Hb 9.6 g/dL, TLC 7,800/cumm, creatinine 0.8 mg/dL. Anaemia explained; nutritional advice given.

RT treatment sheet:
First fraction: 05 Feb 2024
Fraction 10/25 completed on 16-02-2024.
No vomiting today. Mild diarrhoea 2 episodes. Continue supportive care.

Nursing entry: patient reported burning micturition yesterday. Urine routine advised.

Consultant: Dr. R. Chatterjee  
Radiation Oncology
"""

DOC_RCC = """REGIONAL CANCER CENTRE \u2013 SURGICAL ONCOLOGY

Patient: Mr. Arindam Das  
Age/Sex: 63/M  
OPD date: 1st Feb 24

c/o altered bowel habits x 2 months, blood mixed with stool occasionally. Colonoscopy shows ulceroproliferative growth in sigmoid colon. Biopsy suggestive of adenocarcinoma.

CT CAP \u2013 01/2: Circumferential sigmoid wall thickening with pericolic fat stranding. No definite liver metatasis.

Elective anterior resection performed on 02-02-2024 under GA. Post-op stable.

Surgical pathology report:
Specimen received 02.02.2024
Diagnosis: Moderately differentiated adenocarcinoma of sigmoid colon.
Tumour size: 4.1 cm.
Tumour extends into pericolic adipose tissue.
Lymphovascular invasion: Present.
Perineural invasion: Absent.
Resection margins: Negative.
Lymph nodes examined: 18.
Nodes positive: 2/18 nodes.
Pathological stage: pT3N1b (M category based on clinical/radiological workup).

Postoperative review \u2013 12 Feb 2024

Wound healthy, staples removed. Appetite improving. No fever. Bowel movements regular. ECOG PS 1.

Plan: MDT discussion for adjuvant chemotherapy. CBC, LFT, RFT before next visit. Explain treatment schedule and expected toxicities.

Attending: Dr. P. Sengupta, GI Surgical Oncology

Clerical note entered 12/2/24: Patient's surname written as \u201cDey\u201d in one appointment register; operative record and pathology report show Arindam Das. Verify before merging records.
"""

DOC_PEDS = """MEDICAL COLLEGE HOSPITAL, KOLKATA  
Paediatric Haematology / Oncology

Pt name: Ishaan Roy  
Age 7 yrs / M  
Address mentioned in admission register: village Bagnan, Howrah  
Admitted: 01.02.2024

Mother noticed swelling L side neck since 3 weeks, gradually increasing. Fever on and off since yesterday. No cough. No h/o TB contact reported.

Examination:
Temp 100.8 F, HR 112/min. Multiple enlarged cervical lymph nodes, largest approx 3 x 2 cm, firm, non-tender. No significant hepatosplenomegaly.

Initial investigations dated 1/2/24:
Hb 9.4 g/dL; TLC 12,300/cumm; platelets 2.1 lakh/cumm. Peripheral smear: no blasts seen.

USG neck 01 Feb 2024: Multiple enlarged left cervical lymph nodes.

Excision biopsy advised. Histopathology received 02-02-2024: Reactive lymphoid hyperplasia; no evidence of malignancy in examined sections.

Progress note \u2013 2/2
Pt afebrile today. Taking orally. IV fluids stopped. Discharge after review of biopsy and clinical correlation.

Discharge medications:
Paracetamol syrup 250 mg/5 mL, 5 mL orally 6 hourly as needed for fever; maximum daily dose to be confirmed by treating team based on weight.
Review after 7 days, earlier if fever persists or swelling increases.

Discharge summary typed 02 Feb 2024.
Resident: Dr. M. Paul
"""

DOC_DAYCARE = """ONCOLOGY DAY CARE \u2013 FOLLOW UP

Mr Rajes Kumar / Rajesh Kumar  
Age 61/M  
Visit date: 01.02.2024

Known case of adenocarcinoma lung, R upper lobe, with bone metastases. Biopsy done 01 Feb 2023 as per old file. EGFR mutation negative. ALK negative. PD-L1 TPS 10% (report dated 01-03-2023).

Previously received 4 cycles platinum-based chemotherapy, completed 06-23. Now on maintenance systemic treatment as per prior MDT plan.

c/o fatigue and poor appetite x 1 week. No fever. Bone pain controlled on current medication. H/O HTN on regular medication.

Vitals: BP 126/78 mmHg, PR 88/min, SpO2 96% RA. ECOG PS 1.

Labs 1/2/24:
Hb 10.1 g/dL; ANC 2,400/cumm; platelets 1.6 lakh/cumm; creatinine 0.9 mg/dL; bilirubin 0.7 mg/dL.

Treatment administration sheet:
Cycle 5, Day 1 \u2013 01 Feb 2024.
Premedication administered as per protocol.
Antineoplastic agents administered according to signed chemotherapy prescription and body-surface-area calculation.
No immediate infusion reaction observed.
Total IV fluid documented: 500 mL.
Patient observed for 60 minutes after infusion.

Technician entry at 14:20: Port flushed and dressing changed. Name on worksheet: S. Dutta.

Review planned after 3 weeks with CBC, RFT, LFT and interval imaging as indicated.

Consultant signature at end: Dr. A. Mukherjee

Old file index has the name \u201cRajesh Kumar\u201d while the day-care sheet has \u201cRajes Kumar\u201d. Hospital number not present on the photocopied pages; identity confirmation required before record linkage.
"""

DOC_RAD = """Patient: Mr. Kolkata Sen
Age/Sex: 58/M
Scan date: 01.02.2024

CECT abdomen and pelvis for evaluation of suspected colorectal malignancy.

Findings:
Irregular circumferential thickening of the sigmoid colon. Multiple pericolic nodes noted. Liver shows no focal lesion suspicious for metastasis. Both kidneys enhance normally. No hydronephrosis.

Impression:
Sigmoid colon malignancy with regional lymphadenopathy.

Incidental finding: Small left adrenal nodule, indeterminate.

Comparison made with prior CT performed at Victoria Memorial Imaging Centre, Kolkata, on 1/2/23.

Reporting radiologist: Dr. Sen Gupta.

Patient contact address on request form: 5 Park Street, Kolkata.
"""

DOCS_REALISTIC = [
    ('AB-FIELD cardiology note (CCF)', DOC_CARDIOL, '.csv'),
    ('AB-FIELD ortho discharge summary', DOC_ORTHO, '.csv'),
    ('AB-FIELD medicine note (enteric fever)', DOC_MED, '.csv'),
    ('AB-FIELD surgical oncology note', DOC_SURG, '.csv'),
    ('AB-FIELD TATA OPD + IP admission note', DOC_TATA, '.csv'),
    ('AB-FIELD district hospital medicine note', DOC_NADIA, '.csv'),
    ('AB-FIELD radiation oncology note (cervical Ca)', DOC_RT, '.csv'),
    ('AB-FIELD surgical oncology (colon, name variant)', DOC_RCC, '.csv'),
    ('AB-FIELD paediatric oncology note', DOC_PEDS, '.csv'),
    ('AB-FIELD day-care follow-up (name variant)', DOC_DAYCARE, '.csv'),
    ('AB-FIELD radiology CECT (name = city)', DOC_RAD, '.csv'),
]

DOCS = DOCS_CLEAN + DOCS_REALISTIC

# PII tokens that must NOT survive deidentification. Variants of the
# same name are separate tokens (a leak of any spelling counts).
PII_TOKENS = [
    # cardiology note
    'Kamla Devi', 'Kamala Devi', 'Ramlal Verma', 'Ram Lal Verma',
    'Anita Kumari', 'Suresh Pathek', 'Neha Gupta',
    'Sonpur', 'Saran', 'Bihar',
    # ortho discharge
    'Arvind Subramaniam', 'Venkat Raman', 'Joseph T.', 'Lakshmi N',
    'Tambaram', 'Chennai',
    # medicine note (enteric fever)
    'Rajesh Kumar', 'Rajes Kumar', 'Hari Prasad', 'Sunil Chauhan',
    'Meena', 'Priya Nair', 'S. Banerjee',
    'Rampur Khas', 'Sitapur',
    # surgical oncology
    'Sunita Devi', 'Ramesh Yadav', 'Mehra',
    'Bhagwanpur', 'Vaishali',
    # TATA OPD + IP
    'Ananya Mukherjee', 'Ananya Mukherji',
    'Boral', 'Garia', 'South 24 Parganas',
    # district hospital
    'S. Mondal', 'A. Ghosh',
    'Krishnanagar', 'Nadia',
    # radiation oncology
    'R. Chatterjee',
    'Barhampur', 'Murshidabad',
    # regional cancer centre
    'Arindam Das', 'Dey', 'P. Sengupta',
    # paediatric
    'Ishaan Roy', 'M. Paul',
    'Bagnan', 'Howrah',
    # day care
    'S. Dutta', 'A. Mukherjee',
    # radiology CECT
    'Kolkata Sen', 'Sen Gupta', 'Victoria Memorial', 'Park Street',
    'Kolkata',
    # clean docs
    'Bhaskar Kumar', 'Subhojit Das', 'Prasant Roy', 'Anirban Ghosh',
    'S. K. Bose', 'Ritu Mandal',
    'Patia', 'Mahishadal', 'West Medinipur', 'Salt Lake', 'Ghat Road',
    'Apollo Hospital', 'KOLKATA MEDICAL INSTITUTE',
    'MR/26/092837', 'RAD/26/004512', 'HP/26/011111',
    '8412 3456 7890', '841234567890',
    '98312 45678', '9831245678',
    '716130', '700091',
]

# Clinical content that MUST survive (over-redaction check).
# Focused on date-like values (fractions, titers, BP, times, counts),
# durations, ages, and key clinical terms.
CLINICAL_TOKENS = [
    # clinical times (not dates)
    '07:45', '14:20',
    # fractions/counts that look like dates
    '2/12 nodes', '2/18 nodes', '10/25', '25 fractions',
    # vitals with slashes/colons
    'BP 150/94', 'BP 140/90', 'BP 110/70', 'BP 130/84',
    'BP 130/80', 'BP 100/64', 'BP 126/78', 'O 1:160',
    'SpO2 90%', 'SpO2 91%', 'SpO2 94%', 'SpO2 95%', 'SpO2 96%',
    'EF 35%', '102F', '101.4 F', '100.8 F', '108/min', '112/min',
    '88/min', '82/min',
    # lab values
    'Hb 9.8', 'creat 1.4', 'Hb 10.8', 'TLC 15,600', '1.8 lakh',
    'creatinine 1.2', 'ANC 2,400', 'bilirubin 0.7', 'Hb 9.4',
    '2.1 lakh', 'Hb 9.6', 'TLC 7,800', 'creatinine 0.8',
    'creatinine 0.9', 'Hb 10.1', '1.6 lakh', '1.2 lakh',
    # weights / tumour sizes
    '58 kg', '56.5 kg', '4 kg', '5 kg',
    '4 x 3 cm', '4x3.5 cm', '4x3 cm', '5.2 x 4.8 x 4.5 cm',
    '3 x 2 cm', '4.1 cm', '2.5x2x1.8 cm', '12 mm', '1.2 mm',
    # durations / intervals
    '10 days', '3-4 days', '5 days', '7 days', '14 days', '3 days',
    '2 days', '2 wks', '1 wk', '1 mnth', '2 mnths', '4 mnths',
    '3 months', '2 months', '3 weeks', '1 week', '4 yrs',
    '60 minutes', '6 hourly', '8 hourly', '12 hourly', '10 d', '5 d',
    '1 month', '2 weeks',
    # drugs / doses
    'Amlodipine 5mg', 'Lasix 40mg', 'Ecosprin', 'Enoxaparin 40mg',
    'Tramadol 50 mg', 'paracetamol 1g', 'Ceftriaxone 2g',
    'Pantop 40', 'Letrozole 2.5mg', 'Zoledronic acid 4mg',
    'ceftriaxone 1 g', 'salbutamol', 'ipratropium', '2 L/min',
    'cisplatin', '45 Gy', '250 mg/5 mL', '5 mL orally', '500 mL',
    '12 tabs', '30 tabs', '10 tabs',
    # staging / grading
    'BIRADS 5', 'FIGO stage IIIB', 'pT3N1b', 'T3N1', 'cT2 N1 M0',
    'Grade II', 'Grade III', 'Ki-67 25%', 'ECOG PS 1', 'EGFR',
    'ALK', 'PD-L1 TPS 10%', 'ER+ PR+ Her2 neg', 'Nottingham',
    # clinical terms
    'lymph nodes', 'p16', 'D2-40', 'HER2', 'Ki-67', 'metatasis',
    'SLNB', 'MDT', 'LRTI', 'CCF', 'DCM', 'COPD', 'ECG', 'RFT',
    'LFT', 'FNAC', 'USG', 'CXR', 'CECT', 'IDC', 'triple pos', 'EC-T',
    # age must survive deid (not a direct identifier)
    '56 years', '61/F', '91 y/M', 'M/52', '56/M', 'F/46', '48 yrs',
    '63/M', '7 yrs', '61/M', '58/M', '56y',
]

# Dates (shifted, not removed — checked separately).
DATES = [
    # clean docs
    '01/02/2024', '06/02/2024', '12/04/1968',
    '04/02/2024', '02/02/2024', '05/02/2024',
    # field notes — inconsistent formats/separators
    '1.2.24', '28 Jan 24', '1st Feb 24', '30/1/24', 'Oct 2023',
    'mid Feb', '1/2/24', '3/20', '28/1', '5/2', '02-24', '1 Feb 24',
    '20/1', '3-2-24', '14.02.24', '01-02-2024', '02.02.2024',
    '2/2/24', '01 Feb 2024', '12 Feb 2024', '16-02-2024',
    '05 Feb 2024', '02 Feb 2024', '01.02.2024', '1/2/23',
    '01-03-2023', '06-23', '12/2/24',
    # years
    '2015', '2019', '2020', '2023',
]


SAFENET = [
    ('IN_AADHAAR', re.compile(r'\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b')),
    ('MEDICAL_RECORD_NUMBER', re.compile(r'\b[A-Z]{2,3}/\d{2}/\d{4,}\b')),
    ('IN_MOBILE_NUMBER', re.compile(r'\+91\s?\d{5}\s?\d{5}\b')),
]


def build_safenet_spans(text):
    out = []
    for etype, pat in SAFENET:
        for m in pat.finditer(text):
            out.append({'type': etype, 'start': m.start(), 'end': m.end(),
                        'score': 0.95})
    return out


# Entity types that repeat verbatim in a note and should be redacted at
# every occurrence. Dates are excluded: a short date surface (e.g. '2/2') is
# a substring of other dates ('12/2/24'), so blind propagation is unsafe.
PROPAGATE_TYPES = {
    'PERSON', 'LOCATION', 'ORGANIZATION', 'MEDICAL_RECORD_NUMBER',
    'IN_AADHAAR', 'IN_MOBILE_NUMBER', 'IN_PINCODE', 'IN_ABHA', 'IN_UPI',
    'IN_DRIVING_LICENSE', 'PATIENT_ID',
}


def propagate_spans(text, span_list):
    """Extend each identified entity to ALL identical occurrences in text.

    Small models report a repeated name once; de-identification requires
    every occurrence to be redacted. This is deterministic (findall), so the
    recall gap is closed in code, not by asking the LLM to re-list the name.
    `finditer` owns all occurrence discovery (it always re-finds the original
    position, since text[a:b] == surface); input de-duplication uses a
    separate set so single-occurrence entities are not swallowed.
    """
    dedup, input_seen = [], set()
    for s in span_list:
        key = (s['type'], s['start'], s['end'])
        if key in input_seen:
            continue
        input_seen.add(key)
        dedup.append(s)
    out, out_seen = [], set()
    for s in dedup:
        t, a, b = s['type'], s['start'], s['end']
        surface = text[a:b]
        if t not in PROPAGATE_TYPES or not surface.strip():
            key = (t, a, b)
            if key not in out_seen:
                out_seen.add(key)
                out.append(s)
            continue
        for m in re.finditer(re.escape(surface), text):
            key = (t, m.start(), m.end())
            if key in out_seen:
                continue
            out_seen.add(key)
            out.append({'type': t, 'start': m.start(), 'end': m.end(),
                       'score': s.get('score', 0.9)})
    return out


# ---------------------------------------------------------------------------
# Scoring (identical logic to the Approach-A A/B)
# ---------------------------------------------------------------------------

def score(source, out):
    sl, out_l = source.lower(), out.lower()
    leaks = [t for t in PII_TOKENS if t.lower() in sl and t.lower() in out_l]
    lost = [t for t in CLINICAL_TOKENS
            if t.lower() in sl and t.lower() not in out_l]
    unshifted = [d for d in DATES if d in source and d in out]
    return leaks, lost, unshifted
