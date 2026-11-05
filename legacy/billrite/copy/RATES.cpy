      ******************************************************************
      * COPYBOOK:  RATES                                               *
      * SYSTEM:    BILLRITE - TOWN OF NORTHGATE UTILITY BILLING        *
      * PURPOSE:   TARIFF AND POLICY CONSTANTS. ALL PRICES IN DOLLARS. *
      *            RATE CHANGES ARE MADE HERE AND EVERY PROGRAM THAT   *
      *            COPIES THIS BOOK IS THEN RECOMPILED.                *
      *                                                                *
      * HISTORY:   03/14/91  R.DALE    ORIGINAL TARIFF                 *
      *            07/01/93  R.DALE    1993 TARIFF, TABLE BELOW RETIRED*
      *            04/01/96  M.OKAFOR  SUMMER TIER LIMITS BY COUNCIL   *
      *            01/15/98  M.OKAFOR  1998 TARIFF, ADDED LEVY         *
      *            08/09/99  M.OKAFOR  Y2K: CENTURY PIVOT ADDED        *
      ******************************************************************
       01  RATE-CONSTANTS.
      *    --- RESIDENTIAL TARIFF
           05  RT-RES-TIER1-RATE       PIC 9(5)V9(4) VALUE 0.0912.
           05  RT-RES-TIER2-RATE       PIC 9(5)V9(4) VALUE 0.1185.
           05  RT-RES-TIER-LIMIT       PIC 9(5)      VALUE 600.
           05  RT-RES-SUMMER-LIMIT     PIC 9(5)      VALUE 750.
           05  RT-RES-SERVICE          PIC 9(3)V99   VALUE 4.25.
           05  RT-RES-MINIMUM          PIC 9(5)V99   VALUE 8.50.
      *    --- COMMERCIAL TARIFF. SECOND BLOCK IS CHEAPER, ON PURPOSE.
           05  RT-COM-TIER1-RATE       PIC 9(5)V9(4) VALUE 0.1040.
           05  RT-COM-TIER2-RATE       PIC 9(5)V9(4) VALUE 0.0875.
           05  RT-COM-TIER-LIMIT       PIC 9(5)      VALUE 2000.
           05  RT-COM-SUMMER-LIMIT     PIC 9(5)      VALUE 2500.
           05  RT-COM-SERVICE          PIC 9(3)V99   VALUE 11.75.
           05  RT-COM-MINIMUM          PIC 9(5)V99   VALUE 25.00.
      *    --- SUMMER WINDOW, INCLUSIVE MONTH NUMBERS
           05  RT-SUMMER-FIRST-MM      PIC 9(2)      VALUE 06.
           05  RT-SUMMER-LAST-MM       PIC 9(2)      VALUE 09.
      *    --- MUNICIPAL LEVY ON THE CURRENT SUBTOTAL
           05  RT-LEVY-RATE            PIC 9V9(4)    VALUE 0.0250.
      *    --- METER CONSTANTS. DIALS ARE FIVE DIGITS.
           05  RT-METER-MAX            PIC 9(5)      VALUE 99999.
           05  RT-MAX-PLAUSIBLE-USE    PIC 9(5)      VALUE 50000.
      *    --- LATE FEE POLICY
           05  RT-LATE-GRACE-DAYS      PIC 9(3)      VALUE 30.
           05  RT-LATE-RATE            PIC 9V9(4)    VALUE 0.0150.
           05  RT-LATE-MINIMUM         PIC 9(3)V99   VALUE 2.00.
           05  RT-LATE-MAXIMUM         PIC 9(3)V99   VALUE 50.00.
      *    --- TWO-DIGIT YEARS AT OR ABOVE THE PIVOT ARE 19YY
           05  RT-CENTURY-PIVOT        PIC 9(2)      VALUE 50.

      *    --- 1987 WINTER DISCOUNT TABLE. RETIRED BY THE 1993 TARIFF.
      *    --- KEPT BECAUSE NOBODY WAS SURE WHAT STILL READ IT.
       01  RT-WINTER-1987-VALUES.
           05  FILLER                  PIC X(11) VALUE '12000000500'.
           05  FILLER                  PIC X(11) VALUE '01000000750'.
           05  FILLER                  PIC X(11) VALUE '02000000750'.
           05  FILLER                  PIC X(11) VALUE '03000000250'.
       01  RT-WINTER-1987-TABLE REDEFINES RT-WINTER-1987-VALUES.
           05  RT-WINTER-ENTRY         OCCURS 4 TIMES.
               10  RT-WINTER-MM        PIC 9(2).
               10  RT-WINTER-DISC      PIC 9(5)V9(4).
