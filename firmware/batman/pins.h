// Розкладка пінів — docs/connections.md. Одне число — одне місце: тут.
#pragma once

// Керування
#define PIN_SW1_ON    25   // mSW1 ON (3,3 В напряму)
#define PIN_SW2_ON    26   // mSW2 ON
#define PIN_K1        27   // база NPN Q1 -> mREL2 IN1 (HIGH = реле ввімкнене)
#define PIN_K2        13   // база NPN Q2 -> mREL2 IN2
#define PIN_SENS_PWR  14   // база PNP Q3, активний НИЗЬКИЙ: LOW = датчики живляться

// Шини
#define PIN_SDA       21
#define PIN_SCL       22
#define PIN_DPS_TX    17   // UART2 TX -> DPS R (RXI)
#define PIN_DPS_RX    16   // UART2 RX <- DPS T (TXO)
#define PIN_OW         4   // 1-Wire DS18B20 x2

// Входи
#define PIN_FAULT     33   // FAULT датчиків монтажним «І», активний низький
#define PIN_BTN       32   // кнопка на GND
#define PIN_U_LOAD    34   // ADC1_CH6, дільник 100k/4.7k з LOAD+
#define PIN_I_LOAD    39   // ADC1_CH3, mACS3 VIOUT

// I2C
#define I2C_ADDR_ADS  0x48
#define I2C_ADDR_OLED 0x3C

// Тракти (номінали; калібрування зберігається в NVS)
#define ACS_SENS_V_PER_A   0.090f   // ACS711EX при 3,3 В
#define ACS_ZERO_V         1.650f
#define DIV_UB             11.0f    // 100k / 10k
#define DIV_ULOAD          22.28f   // 100k / 4.7k
