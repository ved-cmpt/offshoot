      ******************************************************************
      * COPYBOOK:  BILLREC                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   OUTPUT BILL RECORD. ONE ROW PER ACCEPTED METER READ.*
      *            CARRIES THE AMOUNTS AND THE PRINT LINE FOR THE      *
      *            STATEMENT VENDOR.                                   *
      * LENGTH:    190 BYTES, FIXED.                                   *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL LAYOUT                 *
      *            11/21/97  M.OKAFOR  ADDED CREDIT FIELDS             *
      ******************************************************************
       01  BILL-RECORD.
           05  BL-CUST-ID              PIC X(8).
           05  BL-BILL-DATE            PIC 9(6).
           05  BL-CLASS                PIC X(1).
           05  BL-KWH                  PIC 9(5).
           05  BL-EST-FLAG             PIC X(1).
           05  BL-ROLLOVER-FLAG        PIC X(1).
           05  BL-TIER1-KWH            PIC 9(5).
           05  BL-TIER2-KWH            PIC 9(5).
           05  BL-ENERGY               PIC 9(7)V99.
           05  BL-SERVICE              PIC 9(3)V99.
           05  BL-MIN-FLAG             PIC X(1).
           05  BL-LEVY                 PIC 9(5)V99.
           05  BL-CURRENT              PIC 9(7)V99.
           05  BL-DAYS-OVERDUE         PIC 9(5).
           05  BL-LATE-FEE             PIC 9(3)V99.
           05  BL-WAIVED-FLAG          PIC X(1).
           05  BL-CREDIT-USED          PIC 9(5)V99.
           05  BL-CREDIT-CARRY         PIC 9(5)V99.
           05  BL-ARREARS              PIC 9(7)V99.
           05  BL-TOTAL-DUE            PIC 9(7)V99.
           05  BL-STMT-LINE            PIC X(80).
           05  FILLER                  PIC X(4).
