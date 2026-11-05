      ******************************************************************
      * COPYBOOK:  CUSTREC                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   CUSTOMER MASTER RECORD. ONE ROW PER SERVICE ACCOUNT.*
      * LENGTH:    100 BYTES, FIXED. SORTED ASCENDING ON CUST-ID.      *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL LAYOUT                 *
      *            09/02/94  R.DALE    ADDED SENIOR FLAG               *
      *            11/21/97  M.OKAFOR  ADDED CUST-CREDIT, RESIZED FILL *
      ******************************************************************
       01  CUSTOMER-RECORD.
           05  CUST-ID                 PIC X(8).
           05  CUST-NAME               PIC X(30).
           05  CUST-ADDRESS            PIC X(30).
           05  CUST-CLASS              PIC X(1).
               88  CUST-RESIDENTIAL    VALUE 'R'.
               88  CUST-COMMERCIAL     VALUE 'C'.
           05  CUST-SENIOR-FLAG        PIC X(1).
               88  CUST-IS-SENIOR      VALUE 'Y'.
      *        BALANCE CARRIED FROM EARLIER CYCLES, DOLLARS AND CENTS.
           05  CUST-OVERDUE-BAL        PIC 9(7)V99.
      *        DATE THE BALANCE FELL DUE, YYMMDD. ZERO WHEN NONE.
           05  CUST-DUE-DATE           PIC 9(6).
           05  CUST-CREDIT             PIC 9(5)V99.
           05  FILLER                  PIC X(8).
