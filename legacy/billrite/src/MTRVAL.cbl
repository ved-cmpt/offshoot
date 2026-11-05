       IDENTIFICATION DIVISION.
       PROGRAM-ID. MTRVAL.
       AUTHOR. R DALE.
       INSTALLATION. TOWN OF NORTHGATE DATA PROCESSING.
       DATE-WRITTEN. 03/14/91.
      ******************************************************************
      * PROGRAM:   MTRVAL                                              *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   VALIDATE ONE METER READ AND WORK OUT THE KWH USED   *
      *            SINCE THE PREVIOUS READ. CALLED BY BILLRUN ONCE PER *
      *            READ TRANSACTION.                                   *
      *                                                                *
      * CHECKS, IN THE ORDER APPLIED. THE FIRST FAILURE WINS.          *
      *   1. BOTH READS MUST BE NUMERIC.                               *
      *   2. NEITHER READ MAY BE NEGATIVE.                             *
      *   3. THE READ TYPE MUST BE ACTUAL OR ESTIMATED.                *
      *                                                                *
      * THE DIALS ON OUR METERS ARE FIVE DIGITS AND TURN OVER FROM     *
      * 99999 TO 00000. A CURRENT READ BELOW THE PREVIOUS READ IS      *
      * THEREFORE TAKEN AS A ROLLOVER UNLESS THE USAGE THAT IMPLIES IS *
      * NOT BELIEVABLE, IN WHICH CASE THE READ IS REJECTED.            *
      *                                                                *
      * CHANGE LOG:                                                    *
      *   03/14/91  R.DALE    ORIGINAL VERSION                         *
      *   06/30/95  R.DALE    ESTIMATED READS (CR 95-041)              *
      *   02/11/97  M.OKAFOR  REJECT IMPLAUSIBLE ROLLOVERS (CR 97-012) *
      ******************************************************************
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. NORTHGATE-3090.
       OBJECT-COMPUTER. NORTHGATE-3090.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY RATES.
       COPY ERRCODES.
       01  WS-WORK-FIELDS.
           05  WS-TO-ROLLOVER          PIC 9(6).
           05  WS-ROLLOVER-USE         PIC 9(6).
       LINKAGE SECTION.
       COPY CALLREC.

       PROCEDURE DIVISION USING MTRVAL-PARMS.
       0000-MAIN-CONTROL.
           PERFORM 1000-INITIALIZE THRU 1000-EXIT.
           PERFORM 2000-VALIDATE-READ THRU 2000-EXIT.
           IF MV-OUT-STATUS = ERR-OK
               PERFORM 3000-COMPUTE-USAGE THRU 3000-EXIT
           END-IF.
           IF MV-OUT-STATUS = ERR-OK
               PERFORM 4000-FLAG-ESTIMATE THRU 4000-EXIT
           END-IF.
           GOBACK.

      ******************************************************************
      * RESET THE OUTPUT GROUP. WORKING STORAGE AND LINKAGE BOTH KEEP  *
      * THEIR VALUES BETWEEN CALLS.                                    *
      ******************************************************************
       1000-INITIALIZE.
           MOVE ERR-OK TO MV-OUT-STATUS.
           MOVE ZERO   TO MV-OUT-CONSUMPTION.
           MOVE 'N'    TO MV-OUT-ROLLOVER.
           MOVE SPACE  TO MV-OUT-EST-FLAG.
       1000-EXIT.
           EXIT.

       2000-VALIDATE-READ.
           PERFORM 2100-CHECK-NUMERIC THRU 2100-EXIT.
           IF MV-OUT-STATUS = ERR-OK
               PERFORM 2200-CHECK-SIGN THRU 2200-EXIT
           END-IF.
           IF MV-OUT-STATUS = ERR-OK
               PERFORM 2300-CHECK-READ-TYPE THRU 2300-EXIT
           END-IF.
       2000-EXIT.
           EXIT.

       2100-CHECK-NUMERIC.
           IF MV-IN-PREV-READ IS NOT NUMERIC
              OR MV-IN-CURR-READ IS NOT NUMERIC
               MOVE ERR-READ-NOT-NUMERIC TO MV-OUT-STATUS
           END-IF.
       2100-EXIT.
           EXIT.

       2200-CHECK-SIGN.
           IF MV-IN-PREV-READ < ZERO
              OR MV-IN-CURR-READ < ZERO
               MOVE ERR-READ-NEGATIVE TO MV-OUT-STATUS
           END-IF.
       2200-EXIT.
           EXIT.

       2300-CHECK-READ-TYPE.
           IF MV-IN-READ-TYPE NOT = 'A'
              AND MV-IN-READ-TYPE NOT = 'E'
               MOVE ERR-READ-TYPE TO MV-OUT-STATUS
           END-IF.
       2300-EXIT.
           EXIT.

      ******************************************************************
      * USAGE. EQUAL READS ARE ZERO USE, NOT A ROLLOVER.               *
      ******************************************************************
       3000-COMPUTE-USAGE.
           IF MV-IN-CURR-READ >= MV-IN-PREV-READ
               COMPUTE MV-OUT-CONSUMPTION =
                       MV-IN-CURR-READ - MV-IN-PREV-READ
           ELSE
               PERFORM 3100-COMPUTE-ROLLOVER THRU 3100-EXIT
           END-IF.
       3000-EXIT.
           EXIT.

      ******************************************************************
      * THE METER COUNTS UP TO 99999, ONE MORE TICK TO 00000, THEN ON  *
      * TO THE CURRENT READ.                                           *
      ******************************************************************
       3100-COMPUTE-ROLLOVER.
           COMPUTE WS-TO-ROLLOVER = RT-METER-MAX - MV-IN-PREV-READ.
           COMPUTE WS-ROLLOVER-USE =
                   WS-TO-ROLLOVER + 1 + MV-IN-CURR-READ.
           IF WS-ROLLOVER-USE > RT-MAX-PLAUSIBLE-USE
               MOVE ERR-READ-REGRESSION TO MV-OUT-STATUS
           ELSE
               MOVE WS-ROLLOVER-USE TO MV-OUT-CONSUMPTION
               MOVE 'Y' TO MV-OUT-ROLLOVER
           END-IF.
       3100-EXIT.
           EXIT.

      ******************************************************************
      * AN ESTIMATE BILLS LIKE AN ACTUAL READ. THE FLAG ONLY TELLS THE *
      * STATEMENT TO SAY SO.                                           *
      ******************************************************************
       4000-FLAG-ESTIMATE.
           IF MV-IN-READ-TYPE = 'E'
               MOVE 'E' TO MV-OUT-EST-FLAG
           END-IF.
       4000-EXIT.
           EXIT.
