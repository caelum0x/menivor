/** M7.3: values the data-requests page states, kept next to their source. */

/** Minutes the export download link stays valid (apps/api compliance/export.py EXPORT_URL_EXPIRES). */
export const EXPORT_LINK_MINUTES = 15;

/** Days we have to answer a request we receive by email (GDPR Art. 12: one month; KVKK Art. 13: 30 days). */
export const RESPONSE_DAYS = 30;

/**
 * VERBİS (the Turkish data controllers' registry) status. Kept as a pending
 * statement until counsel confirms whether Menivor must register (master plan
 * MD16). Replace with the registration number or the exemption once confirmed.
 */
export const VERBIS_STATUS =
  "Whether Menivor has to register in VERBİS, the data controllers' registry, is being confirmed with our legal counsel. This page will show the registration or the exemption once it is confirmed.";
