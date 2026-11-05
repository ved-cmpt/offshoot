      ******************************************************************
      * COPYBOOK:  READREC                                             *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   METER READ TRANSACTION FROM THE ROUTE HANDHELDS.    *
      * LENGTH:    40 BYTES, FIXED. SORTED ON CUST-ID THEN READ DATE.  *
      *                                                                *
      * NOTE:      READ VALUES ARRIVE UNEDITED FROM THE HANDHELD       *
      *            UPLOAD, SO THEY MAY HOLD GARBAGE OR A MINUS SIGN.   *
      *            MTRVAL IS THE ONLY PLACE THEY ARE CHECKED.          *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL LAYOUT                 *
      *            06/30/95  R.DALE    ADDED RD-READ-TYPE FOR ESTIMATES*
      ******************************************************************
       01  READ-RECORD.
           05  RD-CUST-ID              PIC X(8).
           05  RD-METER-ID             PIC X(8).
           05  RD-READ-DATE            PIC 9(6).
           05  RD-READ-DATE-R REDEFINES RD-READ-DATE.
               10  RD-READ-YY          PIC 9(2).
               10  RD-READ-MM          PIC 9(2).
               10  RD-READ-DD          PIC 9(2).
           05  RD-PREV-READ            PIC S9(5)
                                       SIGN IS LEADING SEPARATE.
           05  RD-CURR-READ            PIC S9(5)
                                       SIGN IS LEADING SEPARATE.
      *        A = ACTUAL READ, E = ESTIMATED BY THE OFFICE.
           05  RD-READ-TYPE            PIC X(1).
           05  FILLER                  PIC X(5).
