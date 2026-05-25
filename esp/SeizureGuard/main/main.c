#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c.h"
#include "driver/gpio.h"

#define I2C_MASTER_SDA_IO     4
#define I2C_MASTER_SCL_IO     5
#define I2C_MASTER_NUM        I2C_NUM_0
#define I2C_MASTER_FREQ_HZ    100000
#define BUZZER_GPIO           6
#define BUZZER_ACTIVE_LEVEL   1
#define BUZZER_IDLE_LEVEL     0
#define MPU6050_ADDR          0x68
#define MAX30102_ADDR         0x57

#define MOTION_SEIZURE_G      1.5f
#define HR_SEIZURE_BPM        120.0f
#define SPO2_SEIZURE_PERCENT  90.0f
#define FINGER_RED_MIN        50000U
#define FINGER_IR_MIN         50000U
#define FINGER_AC_MIN         80U
#define SENSOR_SAMPLE_COUNT   50
#define SENSOR_SAMPLE_MS      20
#define BPM_MIN_VALID         45.0f
#define BPM_MAX_VALID         180.0f
#define BPM_MAX_JUMP          50.0f
#define TREMOR_MIN_HZ         4.0f
#define TREMOR_MAX_HZ         12.0f
#define SEIZURE_HOLD_WINDOWS  15

static int alarm_state = 0;
static int seizure_hold_counter = 0;
static float last_total_g = 1.0f;
static float ir_dc_level = 0.0f;
static bool pulse_was_high = false;
static TickType_t last_beat_tick = 0;
static float measured_hr = 0.0f;
static float measured_spo2 = 0.0f;

typedef struct {
    float vibration;
    float tremor_hz;
    float hr;
    float spo2;
    bool finger_present;
} sensor_result_t;

static esp_err_t i2c_master_init(void) {
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_MASTER_FREQ_HZ,
    };

    esp_err_t err = i2c_param_config(I2C_MASTER_NUM, &conf);
    if (err != ESP_OK) {
        return err;
    }

    return i2c_driver_install(I2C_MASTER_NUM, conf.mode, 0, 0, 0);
}

static esp_err_t i2c_write_reg(uint8_t device_addr, uint8_t reg_addr, uint8_t value) {
    uint8_t buf[2] = {reg_addr, value};
    return i2c_master_write_to_device(I2C_MASTER_NUM, device_addr, buf, 2, pdMS_TO_TICKS(100));
}

static void mpu6050_init(void) {
    i2c_write_reg(MPU6050_ADDR, 0x6B, 0x00);
}

static void max30102_init(void) {
    i2c_write_reg(MAX30102_ADDR, 0x09, 0x40);
    vTaskDelay(pdMS_TO_TICKS(100));

    i2c_write_reg(MAX30102_ADDR, 0x04, 0x00);
    i2c_write_reg(MAX30102_ADDR, 0x05, 0x00);
    i2c_write_reg(MAX30102_ADDR, 0x06, 0x00);
    i2c_write_reg(MAX30102_ADDR, 0x08, 0x4F);
    i2c_write_reg(MAX30102_ADDR, 0x09, 0x03);
    vTaskDelay(pdMS_TO_TICKS(50));
    i2c_write_reg(MAX30102_ADDR, 0x0A, 0x27);
    i2c_write_reg(MAX30102_ADDR, 0x0C, 0x7F);
    i2c_write_reg(MAX30102_ADDR, 0x0D, 0x7F);
}

static void trigger_buzzer_sequence(void) {
    for (int i = 0; i < 3; i++) {
        gpio_set_level(BUZZER_GPIO, BUZZER_ACTIVE_LEVEL);
        vTaskDelay(pdMS_TO_TICKS(180));
        gpio_set_level(BUZZER_GPIO, BUZZER_IDLE_LEVEL);
        vTaskDelay(pdMS_TO_TICKS(300));
    }
}

static void buzzer_startup_test(void) {
    for (int i = 0; i < 6; i++) {
        gpio_set_level(BUZZER_GPIO, BUZZER_ACTIVE_LEVEL);
        vTaskDelay(pdMS_TO_TICKS(250));
        gpio_set_level(BUZZER_GPIO, BUZZER_IDLE_LEVEL);
        vTaskDelay(pdMS_TO_TICKS(150));
    }
}

static bool read_mpu_total_g(float *total_g) {
    uint8_t mpu_reg = 0x3B;
    uint8_t mpu_d[6];

    if (i2c_master_write_read_device(I2C_MASTER_NUM, MPU6050_ADDR, &mpu_reg, 1, mpu_d, 6, pdMS_TO_TICKS(20)) != ESP_OK) {
        return false;
    }

    int16_t raw_x = (mpu_d[0] << 8) | mpu_d[1];
    int16_t raw_y = (mpu_d[2] << 8) | mpu_d[3];
    int16_t raw_z = (mpu_d[4] << 8) | mpu_d[5];
    float x_g = (float)raw_x / 16384.0f;
    float y_g = (float)raw_y / 16384.0f;
    float z_g = (float)raw_z / 16384.0f;

    *total_g = sqrtf((x_g * x_g) + (y_g * y_g) + (z_g * z_g));
    return true;
}

static bool read_max30102_sample(uint32_t *red, uint32_t *ir) {
    uint8_t max_reg = 0x07;
    uint8_t max_d[6];

    if (i2c_master_write_read_device(I2C_MASTER_NUM, MAX30102_ADDR, &max_reg, 1, max_d, 6, pdMS_TO_TICKS(20)) != ESP_OK) {
        return false;
    }

    *red = ((uint32_t)(max_d[0] & 0x03) << 16) | ((uint32_t)max_d[1] << 8) | max_d[2];
    *ir = ((uint32_t)(max_d[3] & 0x03) << 16) | ((uint32_t)max_d[4] << 8) | max_d[5];
    return true;
}

static void reset_pulse_measurement(void) {
    ir_dc_level = 0.0f;
    pulse_was_high = false;
    last_beat_tick = 0;
    measured_hr = 0.0f;
    measured_spo2 = 0.0f;
}

static void update_heart_rate_from_ir(uint32_t ir, float *window_hr) {
    if (ir_dc_level <= 0.0f) {
        ir_dc_level = (float)ir;
        return;
    }

    ir_dc_level = (ir_dc_level * 0.95f) + ((float)ir * 0.05f);
    float ir_ac = (float)ir - ir_dc_level;
    float threshold = ir_dc_level * 0.003f;
    if (threshold < 100.0f) {
        threshold = 100.0f;
    }

    TickType_t now_tick = xTaskGetTickCount();
    if (!pulse_was_high && ir_ac > threshold) {
        if (last_beat_tick > 0) {
            float interval_ms = (float)pdTICKS_TO_MS(now_tick - last_beat_tick);
            float bpm = 60000.0f / interval_ms;

            if (bpm >= BPM_MIN_VALID && bpm <= BPM_MAX_VALID) {
                bool bpm_is_stable = measured_hr <= 0.0f || fabsf(bpm - measured_hr) <= BPM_MAX_JUMP;

                if (bpm_is_stable) {
                    *window_hr = bpm;
                }
            }
        }

        last_beat_tick = now_tick;
        pulse_was_high = true;
    } else if (pulse_was_high && ir_ac < (threshold * 0.4f)) {
        pulse_was_high = false;
    }
}

static void update_spo2_from_window(uint32_t red_min, uint32_t red_max, uint32_t ir_min, uint32_t ir_max) {
    uint32_t red_ac = red_max - red_min;
    uint32_t ir_ac = ir_max - ir_min;
    uint32_t red_dc = (red_max + red_min) / 2U;
    uint32_t ir_dc = (ir_max + ir_min) / 2U;

    if (red_ac < 50U || ir_ac < 50U || red_dc == 0U || ir_dc == 0U) {
        return;
    }

    float ratio = ((float)red_ac / (float)red_dc) / ((float)ir_ac / (float)ir_dc);
    float spo2 = 110.0f - (25.0f * ratio);

    if (spo2 > 100.0f) {
        spo2 = 100.0f;
    } else if (spo2 < 70.0f) {
        spo2 = 70.0f;
    }

    if (measured_spo2 <= 0.0f) {
        measured_spo2 = spo2;
    } else {
        measured_spo2 = (measured_spo2 * 0.80f) + (spo2 * 0.20f);
    }
}

static sensor_result_t read_sensor_window(void) {
    sensor_result_t result = {
        .vibration = 0.0f,
        .tremor_hz = 0.0f,
        .hr = 0.0f,
        .spo2 = 0.0f,
        .finger_present = false,
    };

    int contact_samples = 0;
    int motion_high_samples = 0;
    int motion_valid_samples = 0;
    float motion_sum = 0.0f;
    float motion_peak = 0.0f;
    float window_hr = 0.0f;
    float total_g_samples[SENSOR_SAMPLE_COUNT];
    uint32_t red_min = UINT32_MAX;
    uint32_t red_max = 0;
    uint32_t ir_min = UINT32_MAX;
    uint32_t ir_max = 0;
    uint64_t red_sum = 0;
    uint64_t ir_sum = 0;

    for (int i = 0; i < SENSOR_SAMPLE_COUNT; i++) {
        float total_g = 1.0f;
        if (read_mpu_total_g(&total_g)) {
            if (total_g > 0.2f && total_g < 4.0f) {
                float gravity_removed = fabsf(total_g - 1.0f);
                float change_speed = fabsf(total_g - last_total_g);
                float sample_motion = gravity_removed + change_speed;

                motion_sum += sample_motion;
                total_g_samples[motion_valid_samples] = total_g;
                motion_valid_samples++;

                if (sample_motion > motion_peak) {
                    motion_peak = sample_motion;
                }

                if (sample_motion >= MOTION_SEIZURE_G) {
                    motion_high_samples++;
                }
            }

            last_total_g = total_g;
        }

        uint32_t red = 0;
        uint32_t ir = 0;
        if (read_max30102_sample(&red, &ir)) {
            if (red > FINGER_RED_MIN && ir > FINGER_IR_MIN) {
                contact_samples++;
                red_sum += red;
                ir_sum += ir;
                update_heart_rate_from_ir(ir, &window_hr);

                if (red < red_min) red_min = red;
                if (red > red_max) red_max = red;
                if (ir < ir_min) ir_min = ir;
                if (ir > ir_max) ir_max = ir;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(SENSOR_SAMPLE_MS));
    }

    if (motion_valid_samples > 0) {
        result.vibration = motion_sum / (float)motion_valid_samples;
        if (motion_high_samples >= 3) {
            result.vibration = motion_peak;
        }

        float total_g_avg = 0.0f;
        for (int i = 0; i < motion_valid_samples; i++) {
            total_g_avg += total_g_samples[i];
        }
        total_g_avg /= (float)motion_valid_samples;

        int crossings = 0;
        for (int i = 1; i < motion_valid_samples; i++) {
            float prev = total_g_samples[i - 1] - total_g_avg;
            float curr = total_g_samples[i] - total_g_avg;
            if ((prev <= 0.0f && curr > 0.0f) || (prev >= 0.0f && curr < 0.0f)) {
                crossings++;
            }
        }

        float window_seconds = ((float)motion_valid_samples * (float)SENSOR_SAMPLE_MS) / 1000.0f;
        if (window_seconds > 0.0f) {
            result.tremor_hz = ((float)crossings / 2.0f) / window_seconds;
        }
    }

    uint32_t red_ac = contact_samples > 0 ? red_max - red_min : 0U;
    uint32_t ir_ac = contact_samples > 0 ? ir_max - ir_min : 0U;
    uint32_t red_avg = contact_samples > 0 ? (uint32_t)(red_sum / (uint64_t)contact_samples) : 0U;
    uint32_t ir_avg = contact_samples > 0 ? (uint32_t)(ir_sum / (uint64_t)contact_samples) : 0U;
    bool enough_contact = contact_samples > ((SENSOR_SAMPLE_COUNT * 3) / 5);
    bool enough_signal_level = red_avg > FINGER_RED_MIN && ir_avg > FINGER_IR_MIN;
    bool enough_pulse_signal = red_ac > FINGER_AC_MIN || ir_ac > FINGER_AC_MIN;

    result.finger_present = enough_contact && enough_signal_level;
    if (result.finger_present) {
        if (window_hr > 0.0f) {
            measured_hr = window_hr;
        }
        if (enough_pulse_signal) {
            update_spo2_from_window(red_min, red_max, ir_min, ir_max);
        }
        result.hr = measured_hr;
        result.spo2 = measured_spo2;
    } else {
        reset_pulse_measurement();
    }

    return result;
}

void app_main(void) {
    ESP_ERROR_CHECK(i2c_master_init());
    vTaskDelay(pdMS_TO_TICKS(100));

    mpu6050_init();
    vTaskDelay(pdMS_TO_TICKS(50));
    max30102_init();

    gpio_reset_pin(BUZZER_GPIO);
    gpio_set_direction(BUZZER_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(BUZZER_GPIO, BUZZER_IDLE_LEVEL);
    buzzer_startup_test();

    while (1) {
        sensor_result_t sensor = read_sensor_window();
        bool strong_motion = sensor.vibration >= MOTION_SEIZURE_G;
        bool tremor_range = sensor.tremor_hz >= TREMOR_MIN_HZ && sensor.tremor_hz <= TREMOR_MAX_HZ;
        bool heart_risk = sensor.finger_present &&
                          ((sensor.hr >= HR_SEIZURE_BPM) ||
                           (sensor.spo2 > 0.0f && sensor.spo2 <= SPO2_SEIZURE_PERCENT));
        const char *status_string = "NORMAL";

        if ((strong_motion && tremor_range && heart_risk) ||
            (strong_motion && tremor_range && seizure_hold_counter > 0)) {
            seizure_hold_counter = SEIZURE_HOLD_WINDOWS;
        }

        if (seizure_hold_counter > 0) {
            status_string = "SEIZURE";
            seizure_hold_counter--;

            if (alarm_state == 0) {
                alarm_state = 1;
                trigger_buzzer_sequence();
                alarm_state = 2;
            }
        } else {
            alarm_state = 0;
            gpio_set_level(BUZZER_GPIO, BUZZER_IDLE_LEVEL);
        }

        printf("{\"vibration\": %.2f, \"tremor_hz\": %.1f, \"hr\": %.1f, \"spo2\": %.1f, \"status\": \"%s\"}\n",
               sensor.vibration, sensor.tremor_hz, sensor.hr, sensor.spo2, status_string);
    }
}
