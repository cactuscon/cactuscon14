#include <Arduino.h>

#define LED A2

#define SOFT_TX_PIN D6
#define BAUD_RATE 9600
#define BIT_TIME (1000000 / BAUD_RATE)

const char* morseForChar(char c);
void morseBlink(const char* s, unsigned int unitMs);
void blinkMorseBLE();

void softSerialWriteByte(uint8_t b) {
  // Start bit
  digitalWrite(SOFT_TX_PIN, LOW);
  delayMicroseconds(BIT_TIME);

  // Data bits (LSB first)
  for (int i = 0; i < 8; i++) {
    digitalWrite(SOFT_TX_PIN, (b & 0x01) ? HIGH : LOW);
    delayMicroseconds(BIT_TIME);
    b >>= 1;
  }

  // Stop bit
  digitalWrite(SOFT_TX_PIN, HIGH);
  delayMicroseconds(BIT_TIME);
}

void softSerialPrint(const char *s) {
  while (*s) {
    softSerialWriteByte(*s++);
  }
}

const char* morseForChar(char c) {
  switch (c) {
    case 'b': case 'B': return "-...";
    case 'l': case 'L': return ".-..";
    case 'e': case 'E': return ".";
    default: return "";
  }
}

void morseBlink(const char* s, unsigned int unitMs) {
  /* Blink a string in Morse using the LED pin. unitMs sets duration of one unit (dot). */
  for (const char* p = s; *p; ++p) {
    char ch = *p;
    if (ch == ' ') {
      delay(unitMs * 7); // word gap
      continue;
    }

    const char* seq = morseForChar(ch);
    for (int i = 0; seq[i]; ++i) {
      char sym = seq[i];
      digitalWrite(LED, HIGH);
      if (sym == '.') {
        delay(unitMs);
      } else if (sym == '-') {
        delay(unitMs * 3);
      }
      digitalWrite(LED, LOW);
      if (seq[i+1]) delay(unitMs); // gap between elements
    }
    delay(unitMs * 3); // gap between letters
  }
}

void setup() {
  pinMode(LED, OUTPUT);
  pinMode(SOFT_TX_PIN, OUTPUT);
  digitalWrite(SOFT_TX_PIN, HIGH);  // idle state
}

void loop() {
  softSerialPrint("78c6772c\r\n");
  morseBlink("BLE", 200); // 200 ms unit -> dot=200ms, dash=600ms
  softSerialPrint("78c6772c\r\n");
  delay(2000);
}