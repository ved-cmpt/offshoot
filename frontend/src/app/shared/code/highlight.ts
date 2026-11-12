/**
 * Syntax colouring for COBOL and C#, small on purpose (ADR-053). It splits text into tokens and
 * never produces markup: templates render each token as text, so source code can never become
 * HTML, whatever it contains. Unknown input is returned as plain text.
 */
export type TokenKind = 'keyword' | 'string' | 'number' | 'comment' | 'type' | 'punct' | 'level' | 'plain';
export type Language = 'cobol' | 'csharp' | 'plain';

export interface Token {
  kind: TokenKind;
  text: string;
}

const COBOL_KEYWORDS = new Set(
  `ACCEPT ADD ADVANCING AFTER ALL ALSO AND ASSIGN AT AUTHOR BEFORE BY CALL CLOSE COMP COMP-3
  COMPUTE CONFIGURATION CONTINUE COPY DATA DELIMITED DISPLAY DIVIDE DIVISION ELSE END END-COMPUTE
  END-EVALUATE END-IF END-PERFORM END-READ END-WRITE ENVIRONMENT EQUAL EVALUATE EXIT EXTEND FD
  FILE FILE-CONTROL FILLER FROM GIVING GO GOBACK GREATER IDENTIFICATION IF IN INITIALIZE
  INPUT INPUT-OUTPUT INTO IS LESS LINAGE LINE LINKAGE MOVE MULTIPLY NEXT NOT NUMERIC OCCURS OF
  OPEN OR ORGANIZATION OTHER OUTPUT PERFORM PIC PICTURE PROCEDURE PROGRAM-ID READ RECORD
  REDEFINES REMAINDER ROUNDED RUN SECTION SELECT SEQUENTIAL SET SIZE SPACE SPACES STOP STRING
  SUBTRACT THAN THEN THRU THROUGH TIMES TO TRUE FALSE UNTIL UPON USING VALUE VALUES VARYING WHEN
  WITH WORKING-STORAGE WRITE ZERO ZEROS ZEROES`.split(/\s+/),
);

const CSHARP_KEYWORDS = new Set(
  `abstract as base bool break byte case catch char checked class const continue decimal default
  delegate do double else enum event explicit extern false finally fixed float for foreach goto if
  implicit in int interface internal is lock long namespace new null object operator out override
  params private protected public readonly record ref return sbyte sealed short sizeof stackalloc
  static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using
  var virtual void volatile while init get set value when with async await yield nameof`.split(/\s+/),
);

const PUNCT = /^[()[\]{};,.:=<>+\-*/!?&|%^~]/;

/** Highlight many lines; C# block comments may span lines. */
export function highlightLines(lines: readonly string[], language: Language): Token[][] {
  if (language === 'cobol') {
    return lines.map(cobolLine);
  }
  if (language === 'csharp') {
    let inComment = false;
    return lines.map((line) => {
      const result = csharpLine(line, inComment);
      inComment = result.inComment;
      return result.tokens;
    });
  }
  return lines.map((line) => [{ kind: 'plain', text: line }]);
}

function push(tokens: Token[], kind: TokenKind, text: string): void {
  if (!text) {
    return;
  }
  const last = tokens[tokens.length - 1];
  if (last && last.kind === kind) {
    last.text += text;
  } else {
    tokens.push({ kind, text });
  }
}

/** Fixed-format COBOL: columns 1-6 are a sequence area, column 7 marks a comment line. */
export function cobolLine(line: string): Token[] {
  const tokens: Token[] = [];
  const indicator = line.charAt(6);
  if (indicator === '*' || indicator === '/') {
    return [{ kind: 'comment', text: line }];
  }
  push(tokens, 'plain', line.slice(0, 7));
  const body = line.slice(7);
  let rest = body;
  let afterPic = false;
  let first = true;
  while (rest.length) {
    const space = /^\s+/.exec(rest);
    if (space) {
      push(tokens, 'plain', space[0]);
      rest = rest.slice(space[0].length);
      continue;
    }
    const inlineComment = /^\*>.*/.exec(rest);
    if (inlineComment) {
      push(tokens, 'comment', inlineComment[0]);
      break;
    }
    const string = /^(['"])(?:(?!\1).)*\1?/.exec(rest);
    if (string) {
      push(tokens, 'string', string[0]);
      rest = rest.slice(string[0].length);
      first = false;
      continue;
    }
    if (afterPic) {
      const picture = /^[^\s.]+(?:\.[^\s]+)*/.exec(rest);
      if (picture) {
        // A picture ends at a space or a full stop that ends the sentence.
        const text = picture[0].replace(/\.$/, '');
        push(tokens, 'type', text);
        rest = rest.slice(text.length);
        afterPic = false;
        continue;
      }
    }
    const word = /^[A-Za-z0-9][A-Za-z0-9-]*/.exec(rest);
    if (word) {
      const text = word[0];
      const upper = text.toUpperCase();
      let kind: TokenKind = 'plain';
      if (first && /^\d{2}$/.test(text)) {
        kind = 'level';
      } else if (/^\d+(?:\.\d+)?$/.test(text) || /^\d+V\d+$/.test(upper)) {
        kind = 'number';
      } else if (COBOL_KEYWORDS.has(upper)) {
        kind = 'keyword';
        afterPic = upper === 'PIC' || upper === 'PICTURE';
      } else if (first && line.charAt(7) !== ' ' && /^[A-Z0-9-]+$/.test(upper)) {
        // A name in area A starts a paragraph or a section.
        kind = 'type';
      }
      // Decimal literals such as 0.0912 keep their point.
      const decimal = /^\d+\.\d+/.exec(rest);
      if (kind === 'number' && decimal) {
        push(tokens, 'number', decimal[0]);
        rest = rest.slice(decimal[0].length);
      } else {
        push(tokens, kind, text);
        rest = rest.slice(text.length);
      }
      first = false;
      continue;
    }
    const mark = PUNCT.exec(rest);
    push(tokens, mark ? 'punct' : 'plain', rest[0]);
    rest = rest.slice(1);
    first = false;
  }
  return tokens;
}

export function csharpLine(line: string, inComment: boolean): { tokens: Token[]; inComment: boolean } {
  const tokens: Token[] = [];
  let rest = line;
  let open = inComment;
  while (rest.length) {
    if (open) {
      const end = rest.indexOf('*/');
      if (end < 0) {
        push(tokens, 'comment', rest);
        return { tokens, inComment: true };
      }
      push(tokens, 'comment', rest.slice(0, end + 2));
      rest = rest.slice(end + 2);
      open = false;
      continue;
    }
    if (rest.startsWith('//')) {
      push(tokens, 'comment', rest);
      break;
    }
    if (rest.startsWith('/*')) {
      open = true;
      push(tokens, 'comment', '/*');
      rest = rest.slice(2);
      continue;
    }
    const space = /^\s+/.exec(rest);
    if (space) {
      push(tokens, 'plain', space[0]);
      rest = rest.slice(space[0].length);
      continue;
    }
    const string = /^[$@]{0,2}"(?:[^"\\]|\\.)*"?/.exec(rest) ?? /^'(?:[^'\\]|\\.)*'?/.exec(rest);
    if (string) {
      push(tokens, 'string', string[0]);
      rest = rest.slice(string[0].length);
      continue;
    }
    const number = /^(?:0x[0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?)(?:[mMdDfFuUlL]{1,2})?\b/.exec(rest);
    if (number) {
      push(tokens, 'number', number[0]);
      rest = rest.slice(number[0].length);
      continue;
    }
    const word = /^[A-Za-z_][A-Za-z0-9_]*/.exec(rest);
    if (word) {
      const text = word[0];
      let kind: TokenKind = 'plain';
      if (CSHARP_KEYWORDS.has(text)) {
        kind = 'keyword';
      } else if (/^[A-Z]/.test(text)) {
        kind = 'type';
      }
      push(tokens, kind, text);
      rest = rest.slice(text.length);
      continue;
    }
    const mark = PUNCT.exec(rest);
    push(tokens, mark ? 'punct' : 'plain', rest[0]);
    rest = rest.slice(1);
  }
  return { tokens, inComment: open };
}

export function languageOf(path: string): Language {
  const lower = path.toLowerCase();
  if (/\.(cbl|cob|cpy)$/.test(lower)) {
    return 'cobol';
  }
  if (lower.endsWith('.cs')) {
    return 'csharp';
  }
  return 'plain';
}
