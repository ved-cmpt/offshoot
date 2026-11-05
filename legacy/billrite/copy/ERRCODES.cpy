      ******************************************************************
      * COPYBOOK:  ERRCODES                                            *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   STATUS CODES RETURNED BY THE CALLED PROGRAMS AND    *
      *            WRITTEN TO ERRFILE, WITH THEIR REPORT WORDING.      *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL CODES                  *
      *            11/21/97  M.OKAFOR  ADDED E10                       *
      ******************************************************************
       01  ERR-CODES.
           05  ERR-OK                  PIC X(3) VALUE 'E00'.
           05  ERR-READ-NOT-NUMERIC    PIC X(3) VALUE 'E01'.
           05  ERR-READ-NEGATIVE       PIC X(3) VALUE 'E02'.
           05  ERR-READ-TYPE           PIC X(3) VALUE 'E03'.
           05  ERR-READ-REGRESSION     PIC X(3) VALUE 'E04'.
           05  ERR-BAD-CLASS           PIC X(3) VALUE 'E05'.
           05  ERR-BAD-MONTH           PIC X(3) VALUE 'E06'.
           05  ERR-BAD-DATE            PIC X(3) VALUE 'E07'.
           05  ERR-CUST-NOT-FOUND      PIC X(3) VALUE 'E08'.
           05  ERR-BAD-USAGE           PIC X(3) VALUE 'E09'.
           05  ERR-BAD-AMOUNT          PIC X(3) VALUE 'E10'.

       01  ERR-MESSAGE-VALUES.
           05  FILLER PIC X(33) VALUE 'E01METER READ NOT NUMERIC'.
           05  FILLER PIC X(33) VALUE 'E02METER READ NEGATIVE'.
           05  FILLER PIC X(33) VALUE 'E03UNKNOWN READ TYPE'.
           05  FILLER PIC X(33) VALUE 'E04READ BELOW PREVIOUS READ'.
           05  FILLER PIC X(33) VALUE 'E05UNKNOWN CUSTOMER CLASS'.
           05  FILLER PIC X(33) VALUE 'E06INVALID BILLING MONTH'.
           05  FILLER PIC X(33) VALUE 'E07INVALID DATE'.
           05  FILLER PIC X(33) VALUE 'E08CUSTOMER NOT ON MASTER'.
           05  FILLER PIC X(33) VALUE 'E09USAGE NOT NUMERIC'.
           05  FILLER PIC X(33) VALUE 'E10AMOUNT NOT NUMERIC'.
       01  ERR-MESSAGE-TABLE REDEFINES ERR-MESSAGE-VALUES.
           05  ERR-MESSAGE-ENTRY       OCCURS 10 TIMES.
               10  ERR-ENTRY-CODE      PIC X(3).
               10  ERR-ENTRY-TEXT      PIC X(30).
