Systemic Therapy Drug Schedule
================================

The Systemic Therapy Drug Schedule module details the specific medications and dosing schedules within a systemic therapy course.

.. note::

   The Systemic Therapy Drug Schedule module is linked to a systemic therapy course and there can be multiple drug schedules for a single course.

   Systemic Therapy Drug Schedule -> Systemic Therapy -> Diagnosis -> Patient

Data Collection Fields
-------------------------

.. list-table:: Systemic Therapy Schedule Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Therapy Agent
     - systemic_therapy_agent
     - The specific medication or agent used in this treatment
   * - Administration Route
     - systemic_therapy_agent_route
     - How the medication was administered (e.g., oral, intravenous, subcutaneous)
   * - Agent Start Date
     - systemic_therapy_agent_start_date
     - The date when this specific medication was started (format: DD/MM/YYYY)
   * - Agent End Date
     - systemic_therapy_agent_end_date
     - The date when this specific medication was stopped (format: DD/MM/YYYY)
   * - Planned Dose
     - systemic_therapy_dose_planned
     - The planned dose for this medication
   * - Administered Dose
     - systemic_therapy_dose_administered
     - The actual dose of medication that was administered
   * - Dose Units
     - systemic_therapy_dose_units
     - The units used for the dose (e.g., mg, mg/m², mg/kg)
