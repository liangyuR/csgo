#include <Mouse.h>

// 定義波特率，需與 Python 端一致
const unsigned long BAUD_RATE = 115200;

void setup() {
  // 初始化 HID 滑鼠功能
  Mouse.begin();
  
  // 初始化序列埠通訊
  Serial.begin(BAUD_RATE);
  
  // 為了安全，LED 亮起表示準備就緒
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW); // 預設關閉 LED
}

void loop() {
  // 檢查是否收到完整的 2 bytes 數據 (dx, dy)
  if (Serial.available() >= 2) {
    // 讀取 X 和 Y 的位移量 (signed byte: -128 ~ 127)
    // Python 端傳送的是 struct.pack('bb', dx, dy)
    char dx = (char)Serial.read();
    char dy = (char)Serial.read();
    
    // 執行滑鼠移動
    // Mouse.move 接受 signed char，直接對應我們的輸入
    if (dx != 0 || dy != 0) {
      Mouse.move(dx, dy, 0);
      
      // 傳輸時閃爍 LED (可選，除錯用，如果要求極度隱蔽可移除)
      // digitalWrite(LED_BUILTIN, HIGH);
      // delay(1);
      // digitalWrite(LED_BUILTIN, LOW);
    }
  }
}
