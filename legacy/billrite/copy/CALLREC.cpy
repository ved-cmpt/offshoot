      ******************************************************************
      * COPYBOOK:  CALLREC                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   PARAMETER BLOCKS FOR THE FOUR CALLED PROGRAMS. EACH *
      *            BLOCK IS AN INPUT GROUP FOLLOWED BY AN OUTPUT GROUP.*
      *            THE PER-RECORD ENTRY PROGRAM READS AND WRITES THESE *
      *            SAME BYTES, SO THE LAYOUTS HERE ARE ITS PROTOCOL.   *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL                        *
      *            11/21/97  M.OKAFOR  ADDED CREDIT FIELDS             *
      ******************************************************************
      *    --- MTRVAL: INPUT 13 BYTES, OUTPUT 10 BYTES
       01  MTRVAL-PARMS.
           05  MV-INPUT.
               10  MV-IN-PREV-READ     PIC S9(5)
                                       SIGN IS LEADING SEPARATE.
               10  MV-IN-CURR-READ     PIC S9(5)
                                       SIGN IS LEADING SEPARATE.
               10  MV-IN-READ-TYPE     PIC X(1).
           05  MV-OUTPUT.
               10  MV-OUT-STATUS       PIC X(3).
               10  MV-OUT-CONSUMPTION  PIC 9(5).
               10  MV-OUT-ROLLOVER     PIC X(1).
               10  MV-OUT-EST-FLAG     PIC X(1).

      *    --- RATECALC: INPUT 8 BYTES, OUTPUT 58 BYTES
       01  RATECALC-PARMS.
           05  RC-INPUT.
               10  RC-IN-CLASS         PIC X(1).
               10  RC-IN-MONTH         PIC 9(2).
               10  RC-IN-KWH           PIC 9(5).
           05  RC-OUTPUT.
               10  RC-OUT-STATUS       PIC X(3).
               10  RC-OUT-TIER-LIMIT   PIC 9(5).
               10  RC-OUT-T1-KWH       PIC 9(5).
               10  RC-OUT-T2-KWH       PIC 9(5).
               10  RC-OUT-ENERGY       PIC 9(7)V99.
               10  RC-OUT-SERVICE      PIC 9(3)V99.
               10  RC-OUT-SUBTOTAL     PIC 9(7)V99.
               10  RC-OUT-MIN-FLAG     PIC X(1).
               10  RC-OUT-LEVY         PIC 9(5)V99.
               10  RC-OUT-TOTAL        PIC 9(7)V99.

      *    --- LATEFEE: INPUT 29 BYTES, OUTPUT 37 BYTES
       01  LATEFEE-PARMS.
           05  LF-INPUT.
               10  LF-IN-BALANCE       PIC 9(7)V99.
               10  LF-IN-DUE-DATE      PIC 9(6).
               10  LF-IN-BILL-DATE     PIC 9(6).
               10  LF-IN-SENIOR        PIC X(1).
               10  LF-IN-CREDIT        PIC 9(5)V99.
           05  LF-OUTPUT.
               10  LF-OUT-STATUS       PIC X(3).
               10  LF-OUT-DAYS         PIC 9(5).
               10  LF-OUT-FEE          PIC 9(3)V99.
               10  LF-OUT-WAIVED       PIC X(1).
               10  LF-OUT-CREDIT-USED  PIC 9(5)V99.
               10  LF-OUT-CREDIT-CARRY PIC 9(5)V99.
               10  LF-OUT-NET-ARREARS  PIC 9(7)V99.

      *    --- STMTGEN: INPUT 82 BYTES, OUTPUT 83 BYTES
       01  STMTGEN-PARMS.
           05  SG-INPUT.
               10  SG-IN-CUST-ID       PIC X(8).
               10  SG-IN-NAME          PIC X(30).
               10  SG-IN-BILL-DATE     PIC 9(6).
               10  SG-IN-BILL-DATE-R REDEFINES SG-IN-BILL-DATE.
                   15  SG-IN-YY        PIC 9(2).
                   15  SG-IN-MM        PIC 9(2).
                   15  SG-IN-DD        PIC 9(2).
               10  SG-IN-KWH           PIC 9(5).
               10  SG-IN-EST-FLAG      PIC X(1).
               10  SG-IN-CURRENT       PIC 9(7)V99.
               10  SG-IN-FEE           PIC 9(3)V99.
               10  SG-IN-ARREARS       PIC 9(7)V99.
               10  SG-IN-TOTAL-DUE     PIC 9(7)V99.
           05  SG-OUTPUT.
               10  SG-OUT-STATUS       PIC X(3).
               10  SG-OUT-LINE         PIC X(80).
