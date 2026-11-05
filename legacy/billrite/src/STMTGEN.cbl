       IDENTIFICATION DIVISION.
       PROGRAM-ID. STMTGEN.
       AUTHOR. R DALE.
       INSTALLATION. TOWN OF NORTHGATE DATA PROCESSING.
       DATE-WRITTEN. 04/09/91.
      ******************************************************************
      * PROGRAM:   STMTGEN                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   FORMAT THE 80-COLUMN PRINT LINE THE STATEMENT       *
      *            VENDOR'S FORMS ARE LAID OUT FOR.                    *
      *                                                                *
      * THE COLUMNS BELOW MATCH THE PRE-PRINTED FORM AND CANNOT MOVE.  *
      * THE AMOUNT BOXES ON THE FORM ARE NARROWER THAN THE AMOUNTS.    *
      *                                                                *
      *   KNOWN PROBLEM, TICKET 96-233, CLOSED WONTFIX: THE TOTAL DUE  *
      *   BOX HOLDS FOUR WHOLE DIGITS. A TOTAL OF 10,000.00 OR MORE    *
      *   LOSES ITS HIGH-ORDER DIGITS ON THE PRINT LINE. THE FULL      *
      *   AMOUNT IS STILL ON THE BILL RECORD. NAMES ARE CUT TO 20      *
      *   CHARACTERS THE SAME WAY.                                     *
      *                                                                *
      * CHANGE LOG:                                                    *
      *   04/09/91  R.DALE    ORIGINAL VERSION                         *
      *   06/30/95  R.DALE    ESTIMATED READ MESSAGE (CR 95-041)       *
      *   10/14/96  R.DALE    TICKET 96-233 REVIEWED, NO CHANGE        *
      ******************************************************************
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. NORTHGATE-3090.
       OBJECT-COMPUTER. NORTHGATE-3090.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY ERRCODES.
       01  WS-MONTH-DAY-VALUES         PIC X(24)
                                       VALUE '312931303130313130313031'.
       01  WS-MONTH-DAY-TABLE REDEFINES WS-MONTH-DAY-VALUES.
           05  WS-MONTH-DAYS           PIC 9(2) OCCURS 12 TIMES.
       01  WS-STATEMENT-LINE.
           05  ST-CUST-ID              PIC X(8).
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-NAME                 PIC X(20).
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-DATE.
               10  ST-DATE-MM          PIC 9(2).
               10  FILLER              PIC X(1) VALUE '/'.
               10  ST-DATE-DD          PIC 9(2).
               10  FILLER              PIC X(1) VALUE '/'.
               10  ST-DATE-YY          PIC 9(2).
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-KWH                  PIC ZZZZ9.
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-EST-MARK             PIC X(1).
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-CURRENT              PIC ZZZZ9.99.
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-FEE                  PIC Z9.99.
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-TOTAL-DUE            PIC ZZZ9.99.
           05  FILLER                  PIC X(1) VALUE SPACE.
           05  ST-MESSAGE              PIC X(10).
       LINKAGE SECTION.
       COPY CALLREC.

       PROCEDURE DIVISION USING STMTGEN-PARMS.
       0000-MAIN-CONTROL.
           PERFORM 1000-INITIALIZE THRU 1000-EXIT.
           PERFORM 2000-VALIDATE-INPUT THRU 2000-EXIT.
           IF SG-OUT-STATUS = ERR-OK
               PERFORM 3000-FORMAT-HEADING THRU 3000-EXIT
               PERFORM 4000-FORMAT-USAGE THRU 4000-EXIT
               PERFORM 5000-FORMAT-AMOUNTS THRU 5000-EXIT
               PERFORM 6000-SELECT-MESSAGE THRU 6000-EXIT
               MOVE WS-STATEMENT-LINE TO SG-OUT-LINE
           END-IF.
           GOBACK.

       1000-INITIALIZE.
           MOVE ERR-OK TO SG-OUT-STATUS.
           MOVE SPACES TO SG-OUT-LINE.
           MOVE SPACES TO ST-MESSAGE.
       1000-EXIT.
           EXIT.

       2000-VALIDATE-INPUT.
           PERFORM 2100-CHECK-DATE THRU 2100-EXIT.
           IF SG-OUT-STATUS = ERR-OK
               PERFORM 2200-CHECK-AMOUNTS THRU 2200-EXIT
           END-IF.
       2000-EXIT.
           EXIT.

      ******************************************************************
      * CHECKED AGAINST THE MONTH TABLE, WHICH ALWAYS GIVES FEBRUARY   *
      * 29 DAYS BECAUSE THIS PROGRAM DOES NOT KNOW THE YEAR'S CENTURY. *
      * LATEFEE HAS ALREADY PASSED THE BILL DATE PROPERLY IN THE BATCH.*
      ******************************************************************
       2100-CHECK-DATE.
           IF SG-IN-BILL-DATE IS NOT NUMERIC
               MOVE ERR-BAD-DATE TO SG-OUT-STATUS
           ELSE
               IF SG-IN-MM < 1 OR SG-IN-MM > 12
                   MOVE ERR-BAD-DATE TO SG-OUT-STATUS
               ELSE
                   IF SG-IN-DD < 1
                      OR SG-IN-DD > WS-MONTH-DAYS (SG-IN-MM)
                       MOVE ERR-BAD-DATE TO SG-OUT-STATUS
                   END-IF
               END-IF
           END-IF.
       2100-EXIT.
           EXIT.

       2200-CHECK-AMOUNTS.
           IF SG-IN-KWH IS NOT NUMERIC
              OR SG-IN-CURRENT IS NOT NUMERIC
              OR SG-IN-FEE IS NOT NUMERIC
              OR SG-IN-ARREARS IS NOT NUMERIC
              OR SG-IN-TOTAL-DUE IS NOT NUMERIC
               MOVE ERR-BAD-AMOUNT TO SG-OUT-STATUS
           END-IF.
       2200-EXIT.
           EXIT.

      ******************************************************************
      * ST-NAME IS 20 CHARACTERS. THE MOVE DROPS THE REST OF THE NAME. *
      ******************************************************************
       3000-FORMAT-HEADING.
           MOVE SG-IN-CUST-ID TO ST-CUST-ID.
           MOVE SG-IN-NAME    TO ST-NAME.
           MOVE SG-IN-MM      TO ST-DATE-MM.
           MOVE SG-IN-DD      TO ST-DATE-DD.
           MOVE SG-IN-YY      TO ST-DATE-YY.
       3000-EXIT.
           EXIT.

       4000-FORMAT-USAGE.
           MOVE SG-IN-KWH      TO ST-KWH.
           MOVE SG-IN-EST-FLAG TO ST-EST-MARK.
       4000-EXIT.
           EXIT.

      ******************************************************************
      * SEE TICKET 96-233 ABOVE. THESE MOVES KEEP THE LOW-ORDER DIGITS *
      * AND DROP THE HIGH-ORDER DIGITS THAT DO NOT FIT THE BOX.        *
      ******************************************************************
       5000-FORMAT-AMOUNTS.
           MOVE SG-IN-CURRENT   TO ST-CURRENT.
           MOVE SG-IN-FEE       TO ST-FEE.
           MOVE SG-IN-TOTAL-DUE TO ST-TOTAL-DUE.
       5000-EXIT.
           EXIT.

      ******************************************************************
      * THE FORM HAS ROOM FOR ONE MESSAGE. AN ESTIMATE OUTRANKS ARREARS*
      ******************************************************************
       6000-SELECT-MESSAGE.
           IF SG-IN-EST-FLAG = 'E'
               MOVE 'ESTIMATED' TO ST-MESSAGE
           ELSE
               IF SG-IN-ARREARS > ZERO
                   MOVE 'PAST DUE' TO ST-MESSAGE
               END-IF
           END-IF.
       6000-EXIT.
           EXIT.
