       IDENTIFICATION DIVISION.
       PROGRAM-ID. LATEFEE.
       AUTHOR. R DALE.
       INSTALLATION. TOWN OF NORTHGATE DATA PROCESSING.
       DATE-WRITTEN. 04/02/91.
      ******************************************************************
      * PROGRAM:   LATEFEE                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   WORK OUT THE LATE FEE ON AN OVERDUE BALANCE, APPLY  *
      *            ANY CREDIT ON THE ACCOUNT, AND RETURN THE ARREARS   *
      *            TO CARRY ONTO THE BILL.                             *
      *                                                                *
      * DATES ARE STORED AS YYMMDD. SINCE THE Y2K REMEDIATION, YEARS   *
      * ARE EXPANDED WITH A FIXED WINDOW: A YEAR AT OR ABOVE THE PIVOT *
      * IN RATES IS 19YY, AND A YEAR BELOW IT IS 20YY.                 *
      *                                                                *
      * THE BALANCE IS NOT REDUCED BETWEEN BILLING CYCLES BY THIS      *
      * PROGRAM. PAYMENTS ARE POSTED TO THE CUSTOMER MASTER BY ANOTHER *
      * SYSTEM, SO THE SAME BALANCE IS ASSESSED AGAIN EACH CYCLE UNTIL *
      * THE MASTER IS REFRESHED.                                       *
      *                                                                *
      * CHANGE LOG:                                                    *
      *   04/02/91  R.DALE    ORIGINAL VERSION                         *
      *   09/02/94  R.DALE    SENIOR WAIVER (COUNCIL ORDER 94-19)      *
      *   11/21/97  M.OKAFOR  ACCOUNT CREDITS (CR 97-088)              *
      *   08/09/99  M.OKAFOR  Y2K CENTURY WINDOW (CR 99-002)           *
      ******************************************************************
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. NORTHGATE-3090.
       OBJECT-COMPUTER. NORTHGATE-3090.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY RATES.
       COPY ERRCODES.
       01  WS-WINDOW-FIELDS.
           05  WS-WINDOW-IN            PIC 9(6).
           05  WS-WINDOW-IN-R REDEFINES WS-WINDOW-IN.
               10  WS-WINDOW-YY        PIC 9(2).
               10  WS-WINDOW-MMDD      PIC 9(4).
           05  WS-WINDOW-OUT           PIC 9(8).
           05  WS-WINDOW-OUT-R REDEFINES WS-WINDOW-OUT.
               10  WS-WINDOW-CC        PIC 9(2).
               10  WS-WINDOW-OUT-YY    PIC 9(2).
               10  WS-WINDOW-OUT-MMDD  PIC 9(4).
       01  WS-DATE-FIELDS.
           05  WS-BILL-YYYYMMDD        PIC 9(8).
           05  WS-DUE-YYYYMMDD         PIC 9(8).
           05  WS-DAY-DIFFERENCE       PIC S9(7).
       01  WS-AMOUNT-FIELDS.
           05  WS-FEE-WORK             PIC 9(7)V99.
           05  WS-GROSS-ARREARS        PIC 9(8)V99.
       LINKAGE SECTION.
       COPY CALLREC.

       PROCEDURE DIVISION USING LATEFEE-PARMS.
       0000-MAIN-CONTROL.
           PERFORM 1000-INITIALIZE THRU 1000-EXIT.
           PERFORM 2000-VALIDATE-INPUT THRU 2000-EXIT.
           IF LF-OUT-STATUS = ERR-OK
               PERFORM 4000-COMPUTE-DAYS-OVERDUE THRU 4000-EXIT
               PERFORM 5000-ASSESS-FEE THRU 5000-EXIT
               PERFORM 6000-APPLY-CREDIT THRU 6000-EXIT
           END-IF.
           GOBACK.

       1000-INITIALIZE.
           MOVE ERR-OK TO LF-OUT-STATUS.
           MOVE ZERO   TO LF-OUT-DAYS.
           MOVE ZERO   TO LF-OUT-FEE.
           MOVE 'N'    TO LF-OUT-WAIVED.
           MOVE ZERO   TO LF-OUT-CREDIT-USED.
           MOVE ZERO   TO LF-OUT-CREDIT-CARRY.
           MOVE ZERO   TO LF-OUT-NET-ARREARS.
           MOVE ZERO   TO WS-BILL-YYYYMMDD.
           MOVE ZERO   TO WS-DUE-YYYYMMDD.
           MOVE ZERO   TO WS-DAY-DIFFERENCE.
           MOVE ZERO   TO WS-FEE-WORK.
           MOVE ZERO   TO WS-GROSS-ARREARS.
       1000-EXIT.
           EXIT.

       2000-VALIDATE-INPUT.
           PERFORM 2100-CHECK-AMOUNTS THRU 2100-EXIT.
           IF LF-OUT-STATUS = ERR-OK
               PERFORM 2200-CHECK-BILL-DATE THRU 2200-EXIT
           END-IF.
           IF LF-OUT-STATUS = ERR-OK
               PERFORM 2300-CHECK-DUE-DATE THRU 2300-EXIT
           END-IF.
       2000-EXIT.
           EXIT.

       2100-CHECK-AMOUNTS.
           IF LF-IN-BALANCE IS NOT NUMERIC
              OR LF-IN-CREDIT IS NOT NUMERIC
               MOVE ERR-BAD-AMOUNT TO LF-OUT-STATUS
           END-IF.
       2100-EXIT.
           EXIT.

       2200-CHECK-BILL-DATE.
           IF LF-IN-BILL-DATE IS NOT NUMERIC
               MOVE ERR-BAD-DATE TO LF-OUT-STATUS
           ELSE
               MOVE LF-IN-BILL-DATE TO WS-WINDOW-IN
               PERFORM 3000-APPLY-CENTURY-WINDOW THRU 3000-EXIT
               MOVE WS-WINDOW-OUT TO WS-BILL-YYYYMMDD
               IF FUNCTION TEST-DATE-YYYYMMDD (WS-BILL-YYYYMMDD)
                  NOT = 0
                   MOVE ERR-BAD-DATE TO LF-OUT-STATUS
               END-IF
           END-IF.
       2200-EXIT.
           EXIT.

      ******************************************************************
      * A ZERO DUE DATE MEANS THERE IS NOTHING OVERDUE, AND IS VALID.  *
      ******************************************************************
       2300-CHECK-DUE-DATE.
           IF LF-IN-DUE-DATE IS NOT NUMERIC
               MOVE ERR-BAD-DATE TO LF-OUT-STATUS
           ELSE
               IF LF-IN-DUE-DATE NOT = ZERO
                   MOVE LF-IN-DUE-DATE TO WS-WINDOW-IN
                   PERFORM 3000-APPLY-CENTURY-WINDOW THRU 3000-EXIT
                   MOVE WS-WINDOW-OUT TO WS-DUE-YYYYMMDD
                   IF FUNCTION TEST-DATE-YYYYMMDD (WS-DUE-YYYYMMDD)
                      NOT = 0
                       MOVE ERR-BAD-DATE TO LF-OUT-STATUS
                   END-IF
               END-IF
           END-IF.
       2300-EXIT.
           EXIT.

      ******************************************************************
      * Y2K WINDOW. 50 THROUGH 99 ARE 1950-1999, 00 THROUGH 49 ARE     *
      * 2000-2049. THIS RUNS OUT IN 2050 AND THAT IS SOMEONE ELSE'S    *
      * PROBLEM.                                                       *
      ******************************************************************
       3000-APPLY-CENTURY-WINDOW.
           IF WS-WINDOW-YY >= RT-CENTURY-PIVOT
               MOVE 19 TO WS-WINDOW-CC
           ELSE
               MOVE 20 TO WS-WINDOW-CC
           END-IF.
           MOVE WS-WINDOW-YY   TO WS-WINDOW-OUT-YY.
           MOVE WS-WINDOW-MMDD TO WS-WINDOW-OUT-MMDD.
       3000-EXIT.
           EXIT.

      ******************************************************************
      * CALENDAR DAYS FROM DUE DATE TO BILL DATE. A DUE DATE THAT IS   *
      * STILL IN THE FUTURE COUNTS AS ZERO DAYS.                       *
      ******************************************************************
       4000-COMPUTE-DAYS-OVERDUE.
           IF LF-IN-BALANCE > ZERO AND LF-IN-DUE-DATE NOT = ZERO
               COMPUTE WS-DAY-DIFFERENCE =
                   FUNCTION INTEGER-OF-DATE (WS-BILL-YYYYMMDD) -
                   FUNCTION INTEGER-OF-DATE (WS-DUE-YYYYMMDD)
               IF WS-DAY-DIFFERENCE > ZERO
                   MOVE WS-DAY-DIFFERENCE TO LF-OUT-DAYS
               END-IF
           END-IF.
       4000-EXIT.
           EXIT.

      ******************************************************************
      * MORE THAN THE GRACE DAYS OVERDUE EARNS A FEE. EXACTLY THE      *
      * GRACE DAYS DOES NOT. SENIORS HAVE THE FEE WAIVED OUTRIGHT, AND *
      * THE WAIVED FLAG ONLY SETS WHEN A FEE WOULD HAVE BEEN DUE.      *
      ******************************************************************
       5000-ASSESS-FEE.
           IF LF-OUT-DAYS > RT-LATE-GRACE-DAYS
               IF LF-IN-SENIOR = 'Y'
                   MOVE 'Y' TO LF-OUT-WAIVED
               ELSE
                   PERFORM 5100-COMPUTE-FEE THRU 5100-EXIT
               END-IF
           END-IF.
       5000-EXIT.
           EXIT.

      ******************************************************************
      * ROUND FIRST, THEN HOLD BETWEEN THE MINIMUM AND THE MAXIMUM.    *
      ******************************************************************
       5100-COMPUTE-FEE.
           COMPUTE WS-FEE-WORK ROUNDED =
                   LF-IN-BALANCE * RT-LATE-RATE.
           IF WS-FEE-WORK < RT-LATE-MINIMUM
               MOVE RT-LATE-MINIMUM TO WS-FEE-WORK
           END-IF.
           IF WS-FEE-WORK > RT-LATE-MAXIMUM
               MOVE RT-LATE-MAXIMUM TO WS-FEE-WORK
           END-IF.
           MOVE WS-FEE-WORK TO LF-OUT-FEE.
       5100-EXIT.
           EXIT.

      ******************************************************************
      * CREDIT OFFSETS THE BALANCE AND THE FEE ONLY. WHAT IS LEFT OF   *
      * IT IS REPORTED AS CARRY AND DOES NOT TOUCH THE CURRENT CHARGE. *
      ******************************************************************
       6000-APPLY-CREDIT.
           COMPUTE WS-GROSS-ARREARS = LF-IN-BALANCE + LF-OUT-FEE.
           IF LF-IN-CREDIT >= WS-GROSS-ARREARS
               MOVE WS-GROSS-ARREARS TO LF-OUT-CREDIT-USED
           ELSE
               MOVE LF-IN-CREDIT TO LF-OUT-CREDIT-USED
           END-IF.
           COMPUTE LF-OUT-CREDIT-CARRY =
                   LF-IN-CREDIT - LF-OUT-CREDIT-USED.
           COMPUTE LF-OUT-NET-ARREARS =
                   WS-GROSS-ARREARS - LF-OUT-CREDIT-USED.
       6000-EXIT.
           EXIT.
