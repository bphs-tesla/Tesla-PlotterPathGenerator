#include <Arduino.h>
#include <AFMotor.h>
#include <EEPROM.h>
#include <Servo.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// --------------------------------------------------
// 펜 플로터 G-code 컨트롤러 (L293D 모터 실드 + 서보 펜)
//
// plotter/gcode.py가 만드는 G-code를 GRBL처럼 받아 실행한다.
// - 한 줄을 받으면 실행을 끝낸 뒤 "ok" 또는 "error:N"으로 응답
// - 시작/리셋 때 "Grbl 1.1h ['$' for help]" 출력 (grbl_sender가 이 문자열로 연결 확인)
// - 실시간 명령: '!' 멈춤, '~' 재개, Ctrl-X 리셋, '?' 상태
//
// 지원 명령:
//   G0 / G1 X Y F : 이동 (G0은 최고 속도, G1은 F 속도)
//   G4 P<초>      : 대기
//   G20 / G21     : inch / mm
//   G90 / G91     : 절대 / 상대 좌표
//   G92 X Y       : 현재 위치를 지정한 좌표로 설정 (원점 맞추기)
//   M3            : 펜 내림 (360° 서보를 PEN_DOWN_MS 동안 돌림, S는 무시)
//   M5            : 펜 올림 (반대로 PEN_UP_MS 동안 돌림)
//   $             : 도움말
//   $U            : 작업 영역 제한 해제 (끝점 측정용)
//   $EL / $EB     : 현재 위치를 왼쪽 / 아래 끝으로 (그 자리가 X=0 / Y=0)
//   $ER / $ET     : 현재 위치를 오른쪽 / 위 끝으로 (작업 영역 크기, EEPROM 저장)
//   $LX / $LY     : $ER / $ET와 같음 (예전 이름)
//   $L            : 작업 영역 보기
//   $RL           : 작업 영역을 기본값으로 되돌림
//   $J=G91 G0 X10 : 조그 이동 (작업 영역 제한 무시, 끝을 처음 정할 때)
//   $ML/$MR/$MB/$MT : 왼쪽 / 오른쪽 / 아래 / 위 끝으로 이동
// 위치와 펜 상태는 EEPROM에 저장되어 재부팅해도 원점이 유지된다
// --------------------------------------------------

// 실제 모터 연결:
// motorA = M1 + M2
// motorB = M3 + M4
AF_Stepper motorA(500, 1);
AF_Stepper motorB(500, 2);

// 펜 서보: 실드의 SER1 단자 = 아두이노 10번 핀 (SERVO_2는 9번)
// Servo 라이브러리는 Timer1을 쓰고 AFMotor 스테퍼는 Timer0/2를 써서 겹치지 않는다
Servo penServo;
const uint8_t PEN_SERVO_PIN = 10;

// 360° (연속 회전) SG90: 각도가 아니라 회전 속도/방향을 정한다.
// 1500us 근처가 정지, 그보다 작으면 한쪽, 크면 반대쪽으로 돈다.
// 펜을 올리고 내릴 때 정해진 시간만큼 돌린 뒤 신호를 끊어 멈춘다.
// 실제 기구에 맞게 보정:
// - 방향이 반대면 PEN_DOWN_US와 PEN_UP_US를 서로 바꾼다
// - 너무 많이/적게 돌면 PEN_DOWN_MS / PEN_UP_MS를 조절한다
const int PEN_DOWN_US = 1700;
const int PEN_UP_US = 1300;
const unsigned long PEN_DOWN_MS = 250;
const unsigned long PEN_UP_MS = 250;

// 전원을 켤 때 펜은 올라가 있다고 가정한다 (켜기 전에 펜을 올려 둔다)
bool penDown = false;

// 실제 기구에 맞게 보정
const float STEPS_PER_MM = 80.0f;

// 모터 방향이 반대로 움직이면 true로 바꾼다
const bool INVERT_X = false;
const bool INVERT_Y = false;
const long SIGN_X = INVERT_X ? -1 : 1;
const long SIGN_Y = INVERT_Y ? -1 : 1;

// 작업 영역 기본값. $LX / $LY로 측정하면 EEPROM에 저장된 값을 쓴다.
// (config의 work_width_mm / work_height_mm를 측정값과 맞춘다)
const float DEFAULT_MAX_X_MM = 300.0f;
const float DEFAULT_MAX_Y_MM = 250.0f;

const uint16_t LIMITS_MAGIC = 0xE7C5;

struct SavedLimits {
  uint16_t magic;
  float maxX;
  float maxY;
};

float maxXMM = DEFAULT_MAX_X_MM;
float maxYMM = DEFAULT_MAX_Y_MM;

// $U로 끄고, 끝점을 기록하면 다시 켜진다
bool limitsOn = true;

// 이번 전원에서 기록한 오른쪽 / 위 끝 (현재 좌표계의 스텝 값)
bool rightKnown = false;
bool topKnown = false;
long rightSteps = 0;
long topSteps = 0;

// 스텝 사이 최소 간격. 이보다 빠르면 모터가 스텝을 놓친다.
// G0과 F가 큰 G1은 이 속도로 움직인다.
const unsigned long MIN_STEP_DELAY_US = 5000;

const float DEFAULT_FEED_MM_MIN = 600.0f;

// 모터 좌표 (스텝 단위). 논리 좌표는 아래 관계로 구한다.
//   X+: motorA+, motorB+ (두 모터 같은 방향)
//   Y+: motorA+, motorB- (두 모터 반대 방향)
//   motorA = x + y, motorB = x - y
//   x = (A + B) / 2,  y = (A - B) / 2
// (INVERT_X / INVERT_Y가 켜지면 x, y 부호가 바뀐다)
long posA = 0;
long posB = 0;

bool absoluteMode = true;
bool inches = false;
float feedMMmin = DEFAULT_FEED_MM_MIN;

bool holding = false;
bool moving = false;
bool jogging = false;  // $J= 이동 중에는 작업 영역 제한을 무시한다
bool resetRequested = false;

char inputLine[64];
uint8_t inputIndex = 0;
bool lineOverflow = false;

// GRBL 오류 코드
const uint8_t ERR_EXPECTED_COMMAND = 1;
const uint8_t ERR_BAD_NUMBER = 2;
const uint8_t ERR_OVERFLOW = 11;
const uint8_t ERR_SOFT_LIMIT = 15;
const uint8_t ERR_UNSUPPORTED = 20;

// --------------------------------------------------
// 좌표 변환
// --------------------------------------------------

long stepsX() { return SIGN_X * (posA + posB) / 2; }
long stepsY() { return SIGN_Y * (posA - posB) / 2; }

void setMotorTarget(long x, long y, long& a, long& b) {
  a = SIGN_X * x + SIGN_Y * y;
  b = SIGN_X * x - SIGN_Y * y;
}

float mmX() { return stepsX() / STEPS_PER_MM; }
float mmY() { return stepsY() / STEPS_PER_MM; }

// --------------------------------------------------
// 출력
// --------------------------------------------------

void printBanner() {
  Serial.println(F("\r\nGrbl 1.1h ['$' for help]"));
}

void printHelp() {
  Serial.println(F("[MSG:Pen plotter G-code controller]"));
  Serial.println(F("[MSG:G0/G1 X Y F, G4 P, G20/G21, G90/G91, G92, M3 S / M5 pen]"));
  Serial.println(F("[MSG:Realtime: ! hold, ~ resume, ? status, Ctrl-X reset]"));
  Serial.println(F("[MSG:Jog example: G91 G0 X10  then  G90]"));
  Serial.println(F("[MSG:Set origin here: G92 X0 Y0]"));
  Serial.println(F("[MSG:Edges: move with $J=, then $EL / $ER / $EB / $ET]"));
  Serial.println(F("[MSG:$L show area, $RL reset area]"));
}

void printLimits() {
  Serial.print(F("[MSG:Area "));
  Serial.print(maxXMM, 2);
  Serial.print(F(" x "));
  Serial.print(maxYMM, 2);
  Serial.print(F(" mm, limits "));
  Serial.print(limitsOn ? F("ON") : F("OFF"));
  // GUI가 설정값과 함께 보여 줄 현재 위치 (원점 = 왼쪽 아래)
  Serial.print(F(", pos "));
  Serial.print(mmX(), 2);
  Serial.print(',');
  Serial.print(mmY(), 2);
  Serial.println(F("]"));
}

// --------------------------------------------------
// 작업 영역 저장 / 불러오기
// --------------------------------------------------

void loadLimits() {
  SavedLimits saved;
  EEPROM.get(0, saved);

  if (saved.magic == LIMITS_MAGIC && saved.maxX > 0 && saved.maxY > 0) {
    maxXMM = saved.maxX;
    maxYMM = saved.maxY;
  }
}

void saveLimits() {
  SavedLimits saved = { LIMITS_MAGIC, maxXMM, maxYMM };
  EEPROM.put(0, saved);
}

// --------------------------------------------------
// 위치 저장 / 불러오기
//
// GUI가 포트를 열 때마다 아두이노가 재부팅되므로, 위치(= 원점 기준 좌표)와
// 펜 상태를 EEPROM에 저장해 두고 켤 때 불러온다. 그래서 원점은 한 번만 정하면 된다.
// EEPROM은 쓸 수 있는 횟수(약 10만 번)가 정해져 있어서, 명령이 끝나고
// SAVE_IDLE_MS 동안 아무 명령도 없을 때만 저장한다 (그림 그리는 중에는 저장하지 않음).
// 주의: 전원이 꺼진 동안 펜을 손으로 옮기면 저장된 위치가 틀어진다.
// --------------------------------------------------

const int POSITION_ADDR = 16;  // SavedLimits 뒤
const uint16_t POSITION_MAGIC = 0xA5C3;
const unsigned long SAVE_IDLE_MS = 1000;

struct SavedPosition {
  uint16_t magic;
  long a;
  long b;
  bool penDown;
};

long savedA = 0;
long savedB = 0;
bool savedPenDown = false;
unsigned long lastCommandMs = 0;

void loadPosition() {
  SavedPosition saved;
  EEPROM.get(POSITION_ADDR, saved);

  if (saved.magic == POSITION_MAGIC) {
    posA = saved.a;
    posB = saved.b;
    penDown = saved.penDown;
  }

  savedA = posA;
  savedB = posB;
  savedPenDown = penDown;
}

void savePositionIfIdle() {
  if (posA == savedA && posB == savedB && penDown == savedPenDown) return;
  if (millis() - lastCommandMs < SAVE_IDLE_MS) return;

  SavedPosition saved = { POSITION_MAGIC, posA, posB, penDown };
  EEPROM.put(POSITION_ADDR, saved);

  savedA = posA;
  savedB = posB;
  savedPenDown = penDown;
}

// --------------------------------------------------
// 끝점 기록
//
// 오른쪽 / 위 끝은 현재 좌표계(원점 = 왼쪽 아래)의 스텝 값으로 기억한다.
// 왼쪽 / 아래 끝을 나중에 다시 정해도 원점이 옮겨진 만큼 함께 옮겨서
// 폭과 높이가 맞게 다시 계산된다. 그래서 버튼을 누르는 순서는 상관없다.
// --------------------------------------------------

void updateAreaFromEdges() {
  bool changed = false;

  if (rightKnown && rightSteps > 0) {
    maxXMM = rightSteps / STEPS_PER_MM;
    changed = true;
  }

  if (topKnown && topSteps > 0) {
    maxYMM = topSteps / STEPS_PER_MM;
    changed = true;
  }

  if (changed) saveLimits();
}

// 현재 물리 위치를 (x, y) 스텝으로 다시 정한다 (G92). 모터는 움직이지 않는다.
void redefinePosition(long x, long y) {
  if (rightKnown) rightSteps += x - stepsX();
  if (topKnown) topSteps += y - stepsY();
  setMotorTarget(x, y, posA, posB);
  updateAreaFromEdges();
}

uint8_t executeLine(char* line);

// $ 명령. 결과 코드: 0 = ok
uint8_t executeSetting(char* cmd) {
  if (cmd[0] == '\0') {
    printHelp();
    return 0;
  }

  // $J=G91 G0 X10: 원점 맞추기용 이동. 작업 영역 제한을 무시하고,
  // 끝나면 G90/G91 상태를 원래대로 돌려놓는다.
  if (cmd[0] == 'J' && cmd[1] == '=') {
    bool savedAbsolute = absoluteMode;
    jogging = true;
    uint8_t result = executeLine(cmd + 2);
    jogging = false;
    absoluteMode = savedAbsolute;
    return result;
  }

  if (strcmp(cmd, "U") == 0) {
    limitsOn = false;
    Serial.println(F("[MSG:Limits OFF. Move to the far end, then $LX / $LY]"));
    return 0;
  }

  // 왼쪽 / 아래 끝: 그 자리를 X=0 / Y=0으로
  if (strcmp(cmd, "EL") == 0 || strcmp(cmd, "EB") == 0) {
    if (cmd[1] == 'L') redefinePosition(0, stepsY());
    else redefinePosition(stepsX(), 0);
    limitsOn = true;
    printLimits();
    return 0;
  }

  // 오른쪽 / 위 끝 ($LX / $LY는 예전 이름)
  if (strcmp(cmd, "ER") == 0 || strcmp(cmd, "ET") == 0 ||
      strcmp(cmd, "LX") == 0 || strcmp(cmd, "LY") == 0) {
    bool isX = (cmd[1] == 'R' || cmd[1] == 'X');
    long value = isX ? stepsX() : stepsY();

    // 끝점은 왼쪽 / 아래 끝보다 +방향에 있어야 한다.
    // 오류로 답하면 GUI가 연결을 끊고, 다시 연결할 때 아두이노가 재부팅되어
    // 원점을 잃으므로 메시지만 보내고 ok로 답한다.
    if (value <= 0) {
      Serial.println(F("[MSG:Not recorded: must be right of / above the left/bottom end]"));
      return 0;
    }

    if (isX) {
      rightKnown = true;
      rightSteps = value;
    } else {
      topKnown = true;
      topSteps = value;
    }

    limitsOn = true;
    updateAreaFromEdges();
    printLimits();
    return 0;
  }

  // 끝으로 이동: $ML 왼쪽, $MR 오른쪽, $MB 아래, $MT 위 (다른 축은 그대로)
  if (cmd[0] == 'M' && cmd[2] == '\0' &&
      (cmd[1] == 'L' || cmd[1] == 'R' || cmd[1] == 'B' || cmd[1] == 'T')) {
    float tx = mmX();
    float ty = mmY();

    if (cmd[1] == 'L') tx = 0;
    else if (cmd[1] == 'R') tx = maxXMM;
    else if (cmd[1] == 'B') ty = 0;
    else ty = maxYMM;

    moving = true;
    moveTo(tx, ty, 1e9f);
    moving = false;
    return 0;
  }

  if (strcmp(cmd, "L") == 0) {
    printLimits();
    return 0;
  }

  if (strcmp(cmd, "RL") == 0) {
    maxXMM = DEFAULT_MAX_X_MM;
    maxYMM = DEFAULT_MAX_Y_MM;
    rightKnown = false;
    topKnown = false;
    limitsOn = true;
    saveLimits();
    printLimits();
    return 0;
  }

  // $X(잠금 해제) 등 나머지 $ 명령은 그냥 받아들인다
  return 0;
}

void printStatus() {
  Serial.print('<');
  // 멈춤은 즉시 끝나므로 GRBL의 "감속 완료" 상태인 Hold:0으로 보고한다
  if (holding) Serial.print(F("Hold:0"));
  else if (moving) Serial.print(F("Run"));
  else Serial.print(F("Idle"));
  Serial.print(F("|MPos:"));
  Serial.print(mmX(), 3);
  Serial.print(',');
  Serial.print(mmY(), 3);
  Serial.println(F(",0.000>"));
}

void printError(uint8_t code) {
  Serial.print(F("error:"));
  Serial.println(code);
}

// --------------------------------------------------
// 실시간 명령
//
// 이동 중에도 계속 확인한다. 실시간 문자가 아니면 읽지 않고
// 남겨 두어 loop()에서 일반 명령으로 처리한다.
// --------------------------------------------------

void pollRealtime() {
  while (Serial.available() > 0) {
    int c = Serial.peek();

    if (c == '!') {
      holding = true;
    } else if (c == '~') {
      holding = false;
    } else if (c == '?') {
      printStatus();
    } else if (c == 0x18) {
      resetRequested = true;
      holding = false;
    } else {
      return;
    }

    Serial.read();
  }
}

// 기다리는 동안에도 실시간 명령을 처리한다. 리셋되면 false.
bool waitUs(unsigned long us) {
  unsigned long start = micros();

  while (micros() - start < us) {
    pollRealtime();
    if (resetRequested) return false;
  }

  while (holding) {
    pollRealtime();
    if (resetRequested) return false;
  }

  return true;
}

// --------------------------------------------------
// 이동
// --------------------------------------------------

void stepA(int dir) {
  motorA.onestep(dir > 0 ? FORWARD : BACKWARD, DOUBLE);
  posA += dir;
}

void stepB(int dir) {
  motorB.onestep(dir > 0 ? FORWARD : BACKWARD, DOUBLE);
  posB += dir;
}

// 목표 좌표(mm, 절대)까지 직선으로 이동. 리셋되면 false.
bool moveTo(float xMM, float yMM, float feed) {
  long tx = lroundf(xMM * STEPS_PER_MM);
  long ty = lroundf(yMM * STEPS_PER_MM);

  long targetA, targetB;
  setMotorTarget(tx, ty, targetA, targetB);

  long dA = targetA - posA;
  long dB = targetB - posB;

  long countA = labs(dA);
  long countB = labs(dB);
  long total = max(countA, countB);

  if (total == 0) return true;

  int dirA = (dA >= 0) ? 1 : -1;
  int dirB = (dB >= 0) ? 1 : -1;

  // 이동 거리와 속도로 반복 한 번당 대기 시간을 구한다
  float dx = (tx - stepsX()) / STEPS_PER_MM;
  float dy = (ty - stepsY()) / STEPS_PER_MM;
  float distance = sqrtf(dx * dx + dy * dy);
  float seconds = distance / (feed / 60.0f);
  unsigned long delayUs = (unsigned long)(seconds * 1e6f / total);
  if (delayUs < MIN_STEP_DELAY_US) delayUs = MIN_STEP_DELAY_US;

  // 두 모터의 스텝을 비례 배분
  long accA = 0;
  long accB = 0;

  for (long i = 0; i < total; i++) {
    accA += countA;
    accB += countB;

    if (accA >= total) {
      stepA(dirA);
      accA -= total;
    }

    if (accB >= total) {
      stepB(dirB);
      accB -= total;
    }

    if (!waitUs(delayUs)) return false;
  }

  return true;
}

// --------------------------------------------------
// 펜 (서보)
// --------------------------------------------------

void setPen(bool down) {
  if (down == penDown) return;

  penServo.attach(PEN_SERVO_PIN);
  penServo.writeMicroseconds(down ? PEN_DOWN_US : PEN_UP_US);
  // 멈춤(!)이 와도 서보가 계속 돌지 않도록 실시간 명령을 보지 않고 기다린다
  delay(down ? PEN_DOWN_MS : PEN_UP_MS);
  // 정지 값(1500us)은 서보마다 조금씩 달라 천천히 돌 수 있으므로 신호를 끊어 멈춘다
  penServo.detach();

  penDown = down;
}

// --------------------------------------------------
// G-code 해석
// --------------------------------------------------

// 공백과 주석을 지우고 대문자로 바꾼다
void normalizeLine(char* line) {
  char* out = line;
  bool inComment = false;

  for (char* p = line; *p; p++) {
    char c = *p;

    if (c == ';') break;
    if (c == '(') { inComment = true; continue; }
    if (c == ')') { inComment = false; continue; }
    if (inComment || c == ' ' || c == '\t') continue;

    *out++ = toupper(c);
  }

  *out = '\0';
}

// 결과 코드: 0 = ok, 그 외 = 오류 코드
uint8_t executeLine(char* line) {
  normalizeLine(line);
  if (line[0] == '\0') return 0;

  if (line[0] == '$') return executeSetting(line + 1);

  int8_t motion = -1;   // 0 = G0, 1 = G1
  int8_t pen = -1;      // 0 = 올림(M5), 1 = 내림(M3/M4)
  bool dwell = false;
  bool setPosition = false;
  bool hasX = false, hasY = false, hasP = false;
  float x = 0, y = 0, p = 0;

  char* cursor = line;

  while (*cursor) {
    char letter = *cursor++;

    if (letter < 'A' || letter > 'Z') return ERR_EXPECTED_COMMAND;

    char* end;
    float value = strtod(cursor, &end);
    if (end == cursor) return ERR_BAD_NUMBER;
    cursor = end;

    switch (letter) {
      case 'G': {
        int code = (int)value;
        if (value != code) return ERR_UNSUPPORTED;

        switch (code) {
          case 0: motion = 0; break;
          case 1: motion = 1; break;
          case 4: dwell = true; break;
          case 20: inches = true; break;
          case 21: inches = false; break;
          case 90: absoluteMode = true; break;
          case 91: absoluteMode = false; break;
          case 92: setPosition = true; break;
          default: return ERR_UNSUPPORTED;
        }
        break;
      }

      case 'M': {
        int code = (int)value;
        if (code == 3 || code == 4) {
          pen = 1;
        } else if (code == 5) {
          pen = 0;
        } else if (code == 0 || code == 2 || code == 30) {
          // 프로그램 정지/종료: 할 일 없음
        } else {
          return ERR_UNSUPPORTED;
        }
        break;
      }

      case 'X': x = value; hasX = true; break;
      case 'Y': y = value; hasY = true; break;
      case 'P': p = value; hasP = true; break;

      case 'F':
        if (value <= 0) return ERR_BAD_NUMBER;
        feedMMmin = inches ? value * 25.4f : value;
        break;

      case 'S':   // 서보 각도: 360° 서보에서는 무시
      case 'Z':   // Z축은 없으므로 무시
        break;

      default:
        return ERR_UNSUPPORTED;
    }
  }

  float unit = inches ? 25.4f : 1.0f;

  // 펜은 같은 줄의 이동보다 먼저 움직인다
  if (pen == 1) setPen(true);
  else if (pen == 0) setPen(false);

  if (dwell) {
    // G4 P0은 앞의 이동이 끝났다는 확인용. 이동은 동기식이라 바로 ok.
    if (hasP && p > 0) waitUs((unsigned long)(p * 1e6f));
    return 0;
  }

  if (setPosition) {
    // 현재 물리 위치를 지정 좌표로 정의 (모터는 움직이지 않음)
    long sx = hasX ? lroundf(x * unit * STEPS_PER_MM) : stepsX();
    long sy = hasY ? lroundf(y * unit * STEPS_PER_MM) : stepsY();
    redefinePosition(sx, sy);
    return 0;
  }

  if (!hasX && !hasY) return 0;

  float cx = mmX();
  float cy = mmY();

  float tx = hasX ? x * unit : (absoluteMode ? cx : 0);
  float ty = hasY ? y * unit : (absoluteMode ? cy : 0);

  if (!absoluteMode) {
    tx += cx;
    ty += cy;
  }

  // 반올림 오차로 끝점에서 거부되지 않도록 약간 여유를 둔다
  const float margin = 0.01f;

  if (limitsOn && !jogging &&
      (tx < -margin || tx > maxXMM + margin ||
       ty < -margin || ty > maxYMM + margin)) {
    // 어떤 좌표가 어느 영역을 벗어났는지 알려 준다 (GUI가 오류 메시지에 붙여 보여 줌)
    Serial.print(F("[MSG:Out of area: X"));
    Serial.print(tx, 2);
    Serial.print(F(" Y"));
    Serial.print(ty, 2);
    Serial.print(F(", area 0~"));
    Serial.print(maxXMM, 2);
    Serial.print(F(" x 0~"));
    Serial.print(maxYMM, 2);
    Serial.println(F(" mm]"));
    return ERR_SOFT_LIMIT;
  }

  // G0은 최고 속도, G1은 F 속도
  float feed = (motion == 1) ? feedMMmin : 1e9f;
  moving = true;
  moveTo(tx, ty, feed);
  moving = false;
  return 0;
}

// --------------------------------------------------
// 리셋
// --------------------------------------------------

void softReset() {
  resetRequested = false;
  holding = false;
  // GRBL처럼 리셋하면 펜을 올린다
  setPen(false);
  absoluteMode = true;
  inches = false;
  feedMMmin = DEFAULT_FEED_MM_MIN;
  inputIndex = 0;
  lineOverflow = false;
  // 위치는 유지한다 (스텝 단위로 이동 중에도 갱신됨)
  printBanner();
}

// --------------------------------------------------
// Arduino
// --------------------------------------------------

void setup() {
  Serial.begin(115200);

  motorA.setSpeed(5);
  motorB.setSpeed(5);

  // 서보는 붙이지 않는다. 신호가 없으면 360° 서보는 멈춰 있다.
  // (켜기 전에 펜을 올려 둔다)

  loadLimits();

  // 저장된 위치가 있으면 이어서 쓴다. 처음 켰을 때(저장값 없음)는
  // 펜이 있는 곳이 원점 (0, 0) = 왼쪽 아래
  loadPosition();

  // 저장된 작업 영역을 오른쪽 / 위 끝으로 삼아, 나중에 왼쪽 / 아래 끝을
  // 다시 정해도 폭과 높이가 맞게 다시 계산되게 한다
  rightKnown = true;
  rightSteps = lroundf(maxXMM * STEPS_PER_MM);
  topKnown = true;
  topSteps = lroundf(maxYMM * STEPS_PER_MM);

  printBanner();
}

void loop() {
  pollRealtime();
  savePositionIfIdle();

  if (resetRequested) {
    softReset();
    return;
  }

  while (Serial.available() > 0) {
    // 줄 중간에 온 실시간 문자도 먼저 처리
    pollRealtime();
    if (resetRequested) {
      softReset();
      return;
    }
    if (Serial.available() == 0) break;

    char c = Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      inputLine[inputIndex] = '\0';

      uint8_t result = lineOverflow ? ERR_OVERFLOW : executeLine(inputLine);

      inputIndex = 0;
      lineOverflow = false;
      lastCommandMs = millis();

      if (resetRequested) {
        // 이동 중 리셋: ok 대신 시작 메시지를 보낸다
        softReset();
        return;
      }

      if (result == 0) {
        Serial.println(F("ok"));
      } else {
        printError(result);
      }
      return;
    }

    if (inputIndex < sizeof(inputLine) - 1) {
      inputLine[inputIndex++] = c;
    } else {
      lineOverflow = true;
    }
  }
}
