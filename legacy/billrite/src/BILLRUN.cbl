       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLRUN.
       AUTHOR. R DALE.
       INSTALLATION. TOWN OF NORTHGATE DATA PROCESSING.
       DATE-WRITTEN. 04/15/91.
      ******************************************************************
      * PROGRAM:   BILLRUN                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   NIGHTLY BILLING BATCH DRIVER.                       *
      *                                                                *
      * MATCHES THE METER READ TRANSACTIONS AGAINST THE CUSTOMER       *
      * MASTER, BOTH SORTED ON CUSTOMER ID, AND FOR EACH READ CALLS:   *
      *                                                                *
      *     MTRVAL    VALIDATE THE READ, WORK OUT THE USAGE            *
      *     RATECALC  PRICE THE USAGE                                  *
      *     LATEFEE   ASSESS THE LATE FEE, APPLY CREDITS               *
      *     STMTGEN   FORMAT THE STATEMENT PRINT LINE                  *
      *                                                                *
      * AN ACCEPTED READ WRITES ONE BILLFILE RECORD. A REJECTED READ   *
      * WRITES ONE ERRFILE RECORD AND NOTHING TO BILLFILE. ONE BAD     *
      * READ DOES NOT STOP THE RUN. A CUSTOMER WITH NO READS THIS RUN  *
      * GETS NO BILL.                                                  *
      *                                                                *
      * THE BILL DATE IS THE READ DATE. THE RUN NEVER LOOKS AT THE     *
      * SYSTEM CLOCK, SO A RERUN OF THE SAME FILES GIVES THE SAME BILLS*
      *                                                                *
      * FILES:     CUSTFILE  INPUT   CUSTOMER MASTER (CUSTREC)         *
      *            READFILE  INPUT   METER READS (READREC)             *
      *            BILLFILE  OUTPUT  BILLS (BILLREC)                   *
      *            ERRFILE   OUTPUT  REJECTED READS                    *
      *                                                                *
      * CHANGE LOG:                                                    *
      *   04/15/91  R.DALE    ORIGINAL VERSION                         *
      *   06/30/95  R.DALE    PASS ESTIMATE FLAG TO BILL (CR 95-041)   *
      *   11/21/97  M.OKAFOR  CREDIT FIELDS ON BILL (CR 97-088)        *
      *   08/09/99  M.OKAFOR  Y2K REVIEW, NO CHANGE HERE (CR 99-002)   *
      ******************************************************************
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. NORTHGATE-3090.
       OBJECT-COMPUTER. NORTHGATE-3090.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTFILE ASSIGN TO "CUSTFILE"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-CUST-STATUS.
           SELECT READFILE ASSIGN TO "READFILE"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-READ-STATUS.
           SELECT BILLFILE ASSIGN TO "BILLFILE"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-BILL-STATUS.
           SELECT ERRFILE ASSIGN TO "ERRFILE"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-ERR-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUSTFILE.
       COPY CUSTREC.
       FD  READFILE.
       COPY READREC.
       FD  BILLFILE.
       COPY BILLREC.
       FD  ERRFILE.
       01  ERROR-RECORD.
           05  ER-CUST-ID              PIC X(8).
           05  ER-READ-DATE            PIC X(6).
           05  ER-CODE                 PIC X(3).
           05  ER-TEXT                 PIC X(30).
           05  ER-RAW-READ             PIC X(40).
       WORKING-STORAGE SECTION.
       COPY ERRCODES.
       COPY CALLREC.
       01  WS-FILE-STATUSES.
           05  WS-CUST-STATUS          PIC X(2).
           05  WS-READ-STATUS          PIC X(2).
           05  WS-BILL-STATUS          PIC X(2).
           05  WS-ERR-STATUS           PIC X(2).
       01  WS-SWITCHES.
           05  WS-READ-EOF-SW          PIC X(1) VALUE 'N'.
               88  WS-READ-EOF         VALUE 'Y'.
           05  WS-CUST-EOF-SW          PIC X(1) VALUE 'N'.
               88  WS-CUST-EOF         VALUE 'Y'.
       01  WS-WORK-FIELDS.
           05  WS-TXN-STATUS           PIC X(3).
           05  WS-ERR-INDEX            PIC 9(2).
           05  WS-TOTAL-DUE            PIC 9(7)V99.
       01  WS-COUNTERS.
           05  WS-CUST-COUNT           PIC 9(7) VALUE ZERO.
           05  WS-READ-COUNT           PIC 9(7) VALUE ZERO.
           05  WS-BILL-COUNT           PIC 9(7) VALUE ZERO.
           05  WS-ERROR-COUNT          PIC 9(7) VALUE ZERO.
           05  WS-AMOUNT-BILLED        PIC 9(9)V99 VALUE ZERO.
           05  WS-RES-BILL-COUNT       PIC 9(7) VALUE ZERO.
           05  WS-RES-AMOUNT           PIC 9(9)V99 VALUE ZERO.
           05  WS-COM-BILL-COUNT       PIC 9(7) VALUE ZERO.
           05  WS-COM-AMOUNT           PIC 9(9)V99 VALUE ZERO.
           05  WS-CUST-BILLED-COUNT    PIC 9(7) VALUE ZERO.
           05  WS-CUST-UNBILLED-COUNT  PIC 9(7) VALUE ZERO.
           05  WS-LAST-BILLED-ID       PIC X(8) VALUE SPACES.
       01  WS-ERROR-TALLY-TABLE.
           05  WS-ERROR-TALLY          PIC 9(7) VALUE ZERO
                                       OCCURS 10 TIMES.
       01  WS-REPORT-FIELDS.
           05  WS-RPT-COUNT            PIC Z,ZZZ,ZZ9.
           05  WS-RPT-AMOUNT           PIC ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       0000-MAIN-CONTROL.
           PERFORM 1000-INITIALIZE THRU 1000-EXIT.
           PERFORM 2000-PROCESS-READ THRU 2000-EXIT
               UNTIL WS-READ-EOF.
           PERFORM 9000-TERMINATE THRU 9000-EXIT.
           STOP RUN.

       1000-INITIALIZE.
           OPEN INPUT  CUSTFILE.
           PERFORM 1100-CHECK-OPEN-CUST THRU 1100-EXIT.
           OPEN INPUT  READFILE.
           PERFORM 1200-CHECK-OPEN-READ THRU 1200-EXIT.
           OPEN OUTPUT BILLFILE.
           OPEN OUTPUT ERRFILE.
           PERFORM 1300-CHECK-OPEN-OUTPUT THRU 1300-EXIT.
           PERFORM 8100-READ-CUSTOMER THRU 8100-EXIT.
           PERFORM 8200-READ-METER-READ THRU 8200-EXIT.
       1000-EXIT.
           EXIT.

       1100-CHECK-OPEN-CUST.
           IF WS-CUST-STATUS NOT = '00'
               DISPLAY 'BILLRUN: CANNOT OPEN CUSTFILE, STATUS '
                       WS-CUST-STATUS UPON SYSERR
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.
       1100-EXIT.
           EXIT.

       1200-CHECK-OPEN-READ.
           IF WS-READ-STATUS NOT = '00'
               DISPLAY 'BILLRUN: CANNOT OPEN READFILE, STATUS '
                       WS-READ-STATUS UPON SYSERR
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.
       1200-EXIT.
           EXIT.

       1300-CHECK-OPEN-OUTPUT.
           IF WS-BILL-STATUS NOT = '00' OR WS-ERR-STATUS NOT = '00'
               DISPLAY 'BILLRUN: CANNOT OPEN OUTPUT FILES, STATUS '
                       WS-BILL-STATUS ' ' WS-ERR-STATUS UPON SYSERR
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.
       1300-EXIT.
           EXIT.

      ******************************************************************
      * ONE PASS FOR ONE READ TRANSACTION. THE UNMATCHED CUSTOMER CASE *
      * LEAVES EARLY THROUGH THE EXIT PARAGRAPH.                       *
      ******************************************************************
       2000-PROCESS-READ.
           ADD 1 TO WS-READ-COUNT.
           PERFORM 2100-MATCH-CUSTOMER THRU 2100-EXIT.
           IF CUST-ID NOT = RD-CUST-ID
               MOVE ERR-CUST-NOT-FOUND TO WS-TXN-STATUS
               PERFORM 7000-WRITE-ERROR THRU 7000-EXIT
               PERFORM 8200-READ-METER-READ THRU 8200-EXIT
               GO TO 2000-EXIT
           END-IF.
           MOVE ERR-OK TO WS-TXN-STATUS.
           PERFORM 3000-VALIDATE-METER THRU 3900-BUILD-EXIT.
           IF WS-TXN-STATUS = ERR-OK
               PERFORM 6000-WRITE-BILL THRU 6000-EXIT
           ELSE
               PERFORM 7000-WRITE-ERROR THRU 7000-EXIT
           END-IF.
           PERFORM 8200-READ-METER-READ THRU 8200-EXIT.
       2000-EXIT.
           EXIT.

      ******************************************************************
      * BOTH FILES ARE IN CUSTOMER ORDER, SO SKIP THE MASTER FORWARD   *
      * UNTIL IT REACHES OR PASSES THIS READ. HIGH-VALUES AT END OF    *
      * MASTER MAKES ANY LATER READ COME UP UNMATCHED.                 *
      ******************************************************************
       2100-MATCH-CUSTOMER.
           PERFORM 8100-READ-CUSTOMER THRU 8100-EXIT
               UNTIL WS-CUST-EOF OR CUST-ID >= RD-CUST-ID.
       2100-EXIT.
           EXIT.

      ******************************************************************
      * THE FOUR CALLS RUN AS ONE PERFORM RANGE, 3000 THRU 3900. EACH  *
      * STEP CHECKS WS-TXN-STATUS, SO THE FIRST FAILURE SKIPS THE REST.*
      ******************************************************************
       3000-VALIDATE-METER.
           MOVE RD-PREV-READ TO MV-IN-PREV-READ.
           MOVE RD-CURR-READ TO MV-IN-CURR-READ.
           MOVE RD-READ-TYPE TO MV-IN-READ-TYPE.
           CALL 'MTRVAL' USING MTRVAL-PARMS.
           MOVE MV-OUT-STATUS TO WS-TXN-STATUS.

       3100-PRICE-USAGE.
           IF WS-TXN-STATUS = ERR-OK
               MOVE CUST-CLASS         TO RC-IN-CLASS
               MOVE RD-READ-MM         TO RC-IN-MONTH
               MOVE MV-OUT-CONSUMPTION TO RC-IN-KWH
               CALL 'RATECALC' USING RATECALC-PARMS
               MOVE RC-OUT-STATUS TO WS-TXN-STATUS
           END-IF.

       3200-ASSESS-ARREARS.
           IF WS-TXN-STATUS = ERR-OK
               MOVE CUST-OVERDUE-BAL TO LF-IN-BALANCE
               MOVE CUST-DUE-DATE    TO LF-IN-DUE-DATE
               MOVE RD-READ-DATE     TO LF-IN-BILL-DATE
               MOVE CUST-SENIOR-FLAG TO LF-IN-SENIOR
               MOVE CUST-CREDIT      TO LF-IN-CREDIT
               CALL 'LATEFEE' USING LATEFEE-PARMS
               MOVE LF-OUT-STATUS TO WS-TXN-STATUS
           END-IF.

       3300-TOTAL-BILL.
           IF WS-TXN-STATUS = ERR-OK
               COMPUTE WS-TOTAL-DUE =
                       RC-OUT-TOTAL + LF-OUT-NET-ARREARS
           END-IF.

       3400-FORMAT-STATEMENT.
           IF WS-TXN-STATUS = ERR-OK
               MOVE CUST-ID            TO SG-IN-CUST-ID
               MOVE CUST-NAME          TO SG-IN-NAME
               MOVE RD-READ-DATE       TO SG-IN-BILL-DATE
               MOVE MV-OUT-CONSUMPTION TO SG-IN-KWH
               MOVE MV-OUT-EST-FLAG    TO SG-IN-EST-FLAG
               MOVE RC-OUT-TOTAL       TO SG-IN-CURRENT
               MOVE LF-OUT-FEE         TO SG-IN-FEE
               MOVE LF-OUT-NET-ARREARS TO SG-IN-ARREARS
               MOVE WS-TOTAL-DUE       TO SG-IN-TOTAL-DUE
               CALL 'STMTGEN' USING STMTGEN-PARMS
               MOVE SG-OUT-STATUS TO WS-TXN-STATUS
           END-IF.
       3900-BUILD-EXIT.
           EXIT.

       6000-WRITE-BILL.
           MOVE SPACES              TO BILL-RECORD.
           MOVE CUST-ID             TO BL-CUST-ID.
           MOVE RD-READ-DATE        TO BL-BILL-DATE.
           MOVE CUST-CLASS          TO BL-CLASS.
           MOVE MV-OUT-CONSUMPTION  TO BL-KWH.
           MOVE MV-OUT-EST-FLAG     TO BL-EST-FLAG.
           MOVE MV-OUT-ROLLOVER     TO BL-ROLLOVER-FLAG.
           MOVE RC-OUT-T1-KWH       TO BL-TIER1-KWH.
           MOVE RC-OUT-T2-KWH       TO BL-TIER2-KWH.
           MOVE RC-OUT-ENERGY       TO BL-ENERGY.
           MOVE RC-OUT-SERVICE      TO BL-SERVICE.
           MOVE RC-OUT-MIN-FLAG     TO BL-MIN-FLAG.
           MOVE RC-OUT-LEVY         TO BL-LEVY.
           MOVE RC-OUT-TOTAL        TO BL-CURRENT.
           MOVE LF-OUT-DAYS         TO BL-DAYS-OVERDUE.
           MOVE LF-OUT-FEE          TO BL-LATE-FEE.
           MOVE LF-OUT-WAIVED       TO BL-WAIVED-FLAG.
           MOVE LF-OUT-CREDIT-USED  TO BL-CREDIT-USED.
           MOVE LF-OUT-CREDIT-CARRY TO BL-CREDIT-CARRY.
           MOVE LF-OUT-NET-ARREARS  TO BL-ARREARS.
           MOVE WS-TOTAL-DUE        TO BL-TOTAL-DUE.
           MOVE SG-OUT-LINE         TO BL-STMT-LINE.
           WRITE BILL-RECORD.
           PERFORM 6100-CHECK-BILL-WRITE THRU 6100-EXIT.
           ADD 1 TO WS-BILL-COUNT.
           ADD WS-TOTAL-DUE TO WS-AMOUNT-BILLED.
           PERFORM 6200-TALLY-BILL THRU 6200-EXIT.
       6000-EXIT.
           EXIT.

       6100-CHECK-BILL-WRITE.
           IF WS-BILL-STATUS NOT = '00'
               DISPLAY 'BILLRUN: BILLFILE WRITE FAILED, STATUS '
                       WS-BILL-STATUS UPON SYSERR
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.
       6100-EXIT.
           EXIT.

      ******************************************************************
      * RUNNING TOTALS BY CLASS, AND DISTINCT CUSTOMERS BILLED. THE    *
      * READS ARE IN CUSTOMER ORDER, SO A NEW ID IS A NEW CUSTOMER.    *
      ******************************************************************
       6200-TALLY-BILL.
           IF CUST-RESIDENTIAL
               ADD 1 TO WS-RES-BILL-COUNT
               ADD WS-TOTAL-DUE TO WS-RES-AMOUNT
           ELSE
               ADD 1 TO WS-COM-BILL-COUNT
               ADD WS-TOTAL-DUE TO WS-COM-AMOUNT
           END-IF.
           IF CUST-ID NOT = WS-LAST-BILLED-ID
               ADD 1 TO WS-CUST-BILLED-COUNT
               MOVE CUST-ID TO WS-LAST-BILLED-ID
           END-IF.
       6200-EXIT.
           EXIT.

       7000-WRITE-ERROR.
           MOVE SPACES        TO ERROR-RECORD.
           MOVE RD-CUST-ID    TO ER-CUST-ID.
           MOVE RD-READ-DATE  TO ER-READ-DATE.
           MOVE WS-TXN-STATUS TO ER-CODE.
           MOVE READ-RECORD   TO ER-RAW-READ.
           PERFORM 7100-LOOKUP-ERROR-TEXT THRU 7100-EXIT.
           WRITE ERROR-RECORD.
           IF WS-ERR-STATUS NOT = '00'
               DISPLAY 'BILLRUN: ERRFILE WRITE FAILED, STATUS '
                       WS-ERR-STATUS UPON SYSERR
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.
           ADD 1 TO WS-ERROR-COUNT.
       7000-EXIT.
           EXIT.

       7100-LOOKUP-ERROR-TEXT.
           PERFORM VARYING WS-ERR-INDEX FROM 1 BY 1
                   UNTIL WS-ERR-INDEX > 10
               IF ERR-ENTRY-CODE (WS-ERR-INDEX) = WS-TXN-STATUS
                   MOVE ERR-ENTRY-TEXT (WS-ERR-INDEX) TO ER-TEXT
                   ADD 1 TO WS-ERROR-TALLY (WS-ERR-INDEX)
               END-IF
           END-PERFORM.
       7100-EXIT.
           EXIT.

       8100-READ-CUSTOMER.
           IF NOT WS-CUST-EOF
               READ CUSTFILE
                   AT END
                       SET WS-CUST-EOF TO TRUE
                       MOVE HIGH-VALUES TO CUST-ID
                   NOT AT END
                       ADD 1 TO WS-CUST-COUNT
               END-READ
           END-IF.
       8100-EXIT.
           EXIT.

       8200-READ-METER-READ.
           READ READFILE
               AT END
                   SET WS-READ-EOF TO TRUE
           END-READ.
       8200-EXIT.
           EXIT.

       9000-TERMINATE.
           PERFORM 9050-DRAIN-MASTER THRU 9050-EXIT
               UNTIL WS-CUST-EOF.
           CLOSE CUSTFILE READFILE BILLFILE ERRFILE.
           COMPUTE WS-CUST-UNBILLED-COUNT =
                   WS-CUST-COUNT - WS-CUST-BILLED-COUNT.
           PERFORM 9100-PRINT-CONTROL-TOTALS THRU 9100-EXIT.
           PERFORM 9200-PRINT-CLASS-TOTALS THRU 9200-EXIT.
           PERFORM 9300-PRINT-ERROR-TALLY THRU 9300-EXIT.
       9000-EXIT.
           EXIT.

      ******************************************************************
      * READ THE REST OF THE MASTER SO THE CUSTOMER COUNT IS COMPLETE. *
      ******************************************************************
       9050-DRAIN-MASTER.
           PERFORM 8100-READ-CUSTOMER THRU 8100-EXIT.
       9050-EXIT.
           EXIT.

      ******************************************************************
      * CONTROL TOTALS FOR THE OPERATOR'S RUN LOG.                     *
      ******************************************************************
       9100-PRINT-CONTROL-TOTALS.
           DISPLAY 'BILLRUN CONTROL TOTALS'.
           MOVE WS-READ-COUNT TO WS-RPT-COUNT.
           DISPLAY '  READS PROCESSED  ' WS-RPT-COUNT.
           MOVE WS-BILL-COUNT TO WS-RPT-COUNT.
           DISPLAY '  BILLS WRITTEN    ' WS-RPT-COUNT.
           MOVE WS-ERROR-COUNT TO WS-RPT-COUNT.
           DISPLAY '  READS REJECTED   ' WS-RPT-COUNT.
           MOVE WS-AMOUNT-BILLED TO WS-RPT-AMOUNT.
           DISPLAY '  TOTAL DUE BILLED ' WS-RPT-AMOUNT.
           MOVE WS-CUST-COUNT TO WS-RPT-COUNT.
           DISPLAY '  CUSTOMERS ON FILE' WS-RPT-COUNT.
           MOVE WS-CUST-BILLED-COUNT TO WS-RPT-COUNT.
           DISPLAY '  CUSTOMERS BILLED ' WS-RPT-COUNT.
           MOVE WS-CUST-UNBILLED-COUNT TO WS-RPT-COUNT.
           DISPLAY '  CUSTOMERS NO BILL' WS-RPT-COUNT.
       9100-EXIT.
           EXIT.

       9200-PRINT-CLASS-TOTALS.
           DISPLAY 'BILLS BY CUSTOMER CLASS'.
           MOVE WS-RES-BILL-COUNT TO WS-RPT-COUNT.
           MOVE WS-RES-AMOUNT TO WS-RPT-AMOUNT.
           DISPLAY '  RESIDENTIAL      ' WS-RPT-COUNT ' ' WS-RPT-AMOUNT.
           MOVE WS-COM-BILL-COUNT TO WS-RPT-COUNT.
           MOVE WS-COM-AMOUNT TO WS-RPT-AMOUNT.
           DISPLAY '  COMMERCIAL       ' WS-RPT-COUNT ' ' WS-RPT-AMOUNT.
       9200-EXIT.
           EXIT.

       9300-PRINT-ERROR-TALLY.
           DISPLAY 'READS REJECTED BY REASON'.
           PERFORM 9310-PRINT-ERROR-LINE THRU 9310-EXIT
               VARYING WS-ERR-INDEX FROM 1 BY 1
               UNTIL WS-ERR-INDEX > 10.
       9300-EXIT.
           EXIT.

       9310-PRINT-ERROR-LINE.
           IF WS-ERROR-TALLY (WS-ERR-INDEX) > ZERO
               MOVE WS-ERROR-TALLY (WS-ERR-INDEX) TO WS-RPT-COUNT
               DISPLAY '  ' ERR-ENTRY-CODE (WS-ERR-INDEX) ' '
                       ERR-ENTRY-TEXT (WS-ERR-INDEX) ' ' WS-RPT-COUNT
           END-IF.
       9310-EXIT.
           EXIT.
