from machine import Pin, freq
from DIYables_MicroPython_Button import Button
import time
import esp32
import sys

def programming_exercise():
    """ To turn on an LED, we need to instruct the badge to operate a pin
    a pin on the badge is just a wire that connects to the LED.
    You can tell the badge to set the pin high, which means let
    electricity flow to the LED, or tell it to set the pin LOW to
    stop the flow of electricity. 
    
    First need to create a variable to store the pin object. You'll want
    to type the following line out, but without the # in front.
    The # in front just tells the badge to ignore the line
    and makes it something for a human to read.
    
    """
    # led_pin = Pin(6, Pin.OUT)
    
    """ Then to turn on the LED you'll simply want to call
    the ON function that is attached to the pin.
    """
    # led_pin.on()
        
def turn_leds_off(leds):
    for l in leds:
        l.off()
def turn_leds_on(leds):
    for l in leds:
        l.on()
        
def clear_code(nvs):
    led_keys = ["led1", "led2", "led3", "led4", "led5", "led6"]
    
    for item in led_keys:
        try:
            nvs.erase_key(item)
            nvs.erase_key("chase")
            nvs.commit()
        except OSError:
            pass
        
    print ("Cleared saved NVS")
    
def load_saved_led_states(nvs, leds):
    led_keys = ["led1", "led2", "led3", "led4", "led5", "led6"]
    
    for index, item in enumerate(led_keys):
        try:
            if nvs.get_i32(item) == 1:
                leds[index].on()
            else:
                leds[index].off()
        except OSError:
            leds[index].off()
            print ("No saved state for {}".format(item))
            
def check_if_all_done(nvs, leds):
    # check if one key is set
    led_keys = ["led1", "led2", "led3", "led4", "led5", "led6"]
    
    for item in led_keys:
        try:
            nvs.get_i32(item)
        except OSError:
            return False
            
    return True

def check_programming_exercise(leds):
    programming_exercise()
    
    if leds[4].value() == 1:
        try:
            nvs.set_i32("led5", 1)
            nvs.commit() 
        except NameError:
            pass

def led_chase(leds):
    leds[0].on()
    time.sleep_ms(40)
    leds[0].off()
    time.sleep_ms(40)
    leds[1].on()
    time.sleep_ms(40)
    leds[1].off()
    time.sleep_ms(40)
    leds[2].on()
    time.sleep_ms(40)
    leds[2].off()
    time.sleep_ms(40)
    leds[3].on()
    time.sleep_ms(40)
    leds[3].off()
    time.sleep_ms(40)
    leds[4].on()
    time.sleep_ms(40)
    leds[4].off()
    time.sleep_ms(40)
    leds[5].on()
    time.sleep_ms(40)
    leds[5].off()
    time.sleep_ms(40)
    
def blink_leds(leds, num_times, delay):
    for i in range(0, num_times):
        turn_leds_off(leds)
        time.sleep_ms(delay)
        turn_leds_on(leds)
        time.sleep_ms(delay)
        turn_leds_off(leds)
        
# -----------------------
# Setup (equivalent to setup())
# -----------------------
time.sleep(2)

# Set CPU frequency to 80 MHz
freq(80_000_000)

# Output pins
led_pins_nums = [7, 2, 1, 5, 6, 4]
leds = [Pin(p, Pin.OUT) for p in led_pins_nums]

nvs = esp32.NVS("cck")

enter_boot = Pin(42, Pin.IN, Pin.PULL_UP)
if enter_boot.value() == 0:
    led_chase(leds)
    blink_leds(leds, 4, 15)
    clear_code(nvs)

# Input pins with internal pull-ups
button1 = Button(15)
button1.set_debounce_time(100)
button2 = Button(40)
button2.set_debounce_time(100)
button3 = Button(41)
button3.set_debounce_time(100)
button_enter = Button(42)
button_enter.set_debounce_time(100)

solder = Pin(18, Pin.IN, Pin.PULL_UP)

out17 = Pin(17, Pin.OUT)
out21 = Pin(21, Pin.OUT)

print("Setup complete")
led1 = 0 
led2 = 0
led3 = 0
led4 = 0
led5 = 0
led6 = 0

Done = [0, 0, 0, 0, 0, 0,]
print ("led on")

blink_leds(leds, 1, 40)

for i in range(4):
    turn_leds_off(leds)
    led_chase(leds)
    blink_leds(leds, 1, 40)
    
blink_leds(leds, 1, 40)


load_saved_led_states(nvs, leds)
    
# -----------------------
# Loop (equivalent to loop())
# -----------------------

check_programming_exercise(leds)

pswd_gues1 = ""
pswd_gues2 = ""
pswd_gues3 = ""

import random

digits = [1, 2, 3]
code = ""
for i in range(2):
    code += str(random.choice(digits))
print ("final code: ", code)

while True:
    try:
        if nvs.get_i32("chase") == 1:
            led_chase(leds)
    except OSError:
        pass
    
    # Buttons are ACTIVE LOW
    button1.loop()
    button2.loop()
    button3.loop()
    button_enter.loop()
#Any print command is for debugging if you are makeing changes you this system to help you.    
    if button1.is_pressed():
        print("Button 1 pressed")
        pswd_gues1 += "1"
    if button2.is_pressed():
        print("Button 2 pressed")
        pswd_gues1 += "2"
    if button3.is_pressed():
        print("Button 3 pressed")
        pswd_gues1 += "3"        
    if button_enter.is_pressed():
        print("Button Enter pressed")
        if pswd_gues1 == "2312":
            print ("pswrd correct")
            pswd_gues1 = ""
            print ("led on")
            nvs.set_i32("led1", 1)
            leds[0].on()
            Done[0] = 1
        elif pswd_gues1 == "3221":
            print ("pswrd correct")
            pswd_gues1 = ""
            print ("led on")
            nvs.set_i32("led2", 1)
            leds[1].on()
            Done[1] = 1
        elif pswd_gues1 == "1332":
            print ("pswrd correct")
            pswd_gues1 = ""
            print ("led on")
            nvs.set_i32("led3", 1)
            leds[2].on()
            Done[2] = 1
        elif pswd_gues1 == "3223":
            print ("pswrd correct")
            pswd_gues1 = ""
            print ("led on")
            nvs.set_i32("led4", 1)
            leds[3].on()
            Done[3] = 1
        else: 
            time.sleep_ms(1)
            turn_leds_off(leds)
            time.sleep_ms(150)
            turn_leds_on(leds)
            time.sleep_ms(150)
            turn_leds_off(leds)
            pswd_gues1 = ""
            load_saved_led_states(nvs, leds)
        nvs.commit()
    if solder.value() == 0:
        leds[5].on()
        nvs.set_i32("led6", 1)
        nvs.commit()  
   
    if check_if_all_done(nvs, leds):
        if button1.is_pressed():
            print("Button 1 pressed")
            pswd_gues3 += "1"
        if button2.is_pressed():
            print("Button 2 pressed")
            pswd_gues3 += "2"
        if button3.is_pressed():
            print("Button 3 pressed")
            pswd_gues3 += "3"
        if button_enter.is_pressed():
            print("Button Enter pressed")
            print(code)
            if pswd_gues3 == code:
                print ("pswrd correct")
                pswd_gues3 = ""
                print ("led on")
                for i in range(3):
                    led_chase(leds)
                digits = [1, 2, 3]
                code = ""
                for i in range(2):
                    code += str(random.choice(digits))
                    load_saved_led_states(nvs, leds)
                    nvs.set_i32("chase", 1)
                    nvs.commit()
                while True:
                    led_chase(leds)
            if not pswd_gues3 == code: 
                time.sleep_ms(1)
                turn_leds_off(leds)
                time.sleep_ms(150)
                turn_leds_on(leds)
                time.sleep_ms(150)
                turn_leds_off(leds)
                load_saved_led_states(nvs, leds)
            pswd_gues3 = ""
    else:
        check_programming_exercise(leds)



