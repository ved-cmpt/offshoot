       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRCALL.
      ******************************************************************
      * PROGRAM:   BRCALL                                              *
      * SYSTEM:    LEGACYLENS TEST HARNESS, NOT PART OF BILLRITE       *
      * PURPOSE:   CALL ONE BILLRITE MODULE ONE RECORD AT A TIME.      *
      *                                                                *
      * USAGE:     BRCALL MTRVAL|RATECALC|LATEFEE|STMTGEN              *
      *                                                                *
      * EACH LINE ON STDIN IS ONE INPUT RECORD, LAID OUT AS THE MODULE *
      * INPUT GROUP IN CALLREC. EACH INPUT LINE PRODUCES EXACTLY ONE   *
      * LINE ON STDOUT, LAID OUT AS THE MODULE OUTPUT GROUP. EXIT CODE *
      * 0 MEANS THE RECORDS WERE PROCESSED, AND A RECORD THE MODULE    *
      * REJECTS IS STILL A NORMAL RECORD WITH ITS STATUS CODE. EXIT    *
      * CODE 2 IS AN UNKNOWN MODULE NAME, 3 IS A STDIN READ FAILURE.   *
      ******************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT STDIN-FILE ASSIGN TO KEYBOARD
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STDIN-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  STDIN-FILE.
       01  STDIN-RECORD                PIC X(256).
       WORKING-STORAGE SECTION.
       COPY CALLREC.
       01  WS-STDIN-STATUS             PIC X(2).
           88  WS-STDIN-OK             VALUE '00' '04' '06'.
           88  WS-STDIN-END            VALUE '10'.
       01  WS-MODULE                   PIC X(32).
           88  WS-MODULE-MTRVAL        VALUE 'MTRVAL'.
           88  WS-MODULE-RATECALC      VALUE 'RATECALC'.
           88  WS-MODULE-LATEFEE       VALUE 'LATEFEE'.
           88  WS-MODULE-STMTGEN       VALUE 'STMTGEN'.
       01  WS-EOF-SW                   PIC X(1) VALUE 'N'.
           88  WS-EOF                  VALUE 'Y'.

       PROCEDURE DIVISION.
       0000-MAIN-CONTROL.
           ACCEPT WS-MODULE FROM COMMAND-LINE.
           IF NOT WS-MODULE-MTRVAL AND NOT WS-MODULE-RATECALC
              AND NOT WS-MODULE-LATEFEE AND NOT WS-MODULE-STMTGEN
               DISPLAY 'BRCALL: UNKNOWN MODULE ' WS-MODULE UPON SYSERR
               MOVE 2 TO RETURN-CODE
               STOP RUN
           END-IF.
           OPEN INPUT STDIN-FILE.
           PERFORM 1000-READ-INPUT THRU 1000-EXIT.
           PERFORM 2000-CALL-MODULE THRU 2000-EXIT UNTIL WS-EOF.
           CLOSE STDIN-FILE.
           STOP RUN.

       1000-READ-INPUT.
           READ STDIN-FILE.
           IF WS-STDIN-END
               SET WS-EOF TO TRUE
           ELSE
               IF NOT WS-STDIN-OK
                   DISPLAY 'BRCALL: STDIN READ FAILED, STATUS '
                           WS-STDIN-STATUS UPON SYSERR
                   MOVE 3 TO RETURN-CODE
                   SET WS-EOF TO TRUE
               END-IF
           END-IF.
       1000-EXIT.
           EXIT.

       2000-CALL-MODULE.
           EVALUATE TRUE
               WHEN WS-MODULE-MTRVAL
                   PERFORM 3000-CALL-MTRVAL THRU 3000-EXIT
               WHEN WS-MODULE-RATECALC
                   PERFORM 4000-CALL-RATECALC THRU 4000-EXIT
               WHEN WS-MODULE-LATEFEE
                   PERFORM 5000-CALL-LATEFEE THRU 5000-EXIT
               WHEN WS-MODULE-STMTGEN
                   PERFORM 6000-CALL-STMTGEN THRU 6000-EXIT
           END-EVALUATE.
           PERFORM 1000-READ-INPUT THRU 1000-EXIT.
       2000-EXIT.
           EXIT.

       3000-CALL-MTRVAL.
           MOVE STDIN-RECORD TO MV-INPUT.
           CALL 'MTRVAL' USING MTRVAL-PARMS.
           DISPLAY MV-OUTPUT.
       3000-EXIT.
           EXIT.

       4000-CALL-RATECALC.
           MOVE STDIN-RECORD TO RC-INPUT.
           CALL 'RATECALC' USING RATECALC-PARMS.
           DISPLAY RC-OUTPUT.
       4000-EXIT.
           EXIT.

       5000-CALL-LATEFEE.
           MOVE STDIN-RECORD TO LF-INPUT.
           CALL 'LATEFEE' USING LATEFEE-PARMS.
           DISPLAY LF-OUTPUT.
       5000-EXIT.
           EXIT.

       6000-CALL-STMTGEN.
           MOVE STDIN-RECORD TO SG-INPUT.
           CALL 'STMTGEN' USING STMTGEN-PARMS.
           DISPLAY SG-OUTPUT.
       6000-EXIT.
           EXIT.
