#!/usr/bin/python
# -*- coding:utf-8 -*-
import serial
import RPi.GPIO as GPIO
from mpu6050 import mpu6050

Temp = '0123456789ABCDEF*'


class config(object):
    FORCE  = 17
    STANDBY= 4
    def __init__(self, baudrate = 9600, mpu_address=0x68):
        self.serial = serial.Serial("/dev/ttyS0",baudrate)
        self.mpu = mpu6050(mpu_address)
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.FORCE, GPIO.IN)
        GPIO.setup(self.STANDBY, GPIO.OUT)
        GPIO.output(self.STANDBY, GPIO.HIGH)
        
    def Uart_SendByte(self, value): 
        self.serial.write(value) 
        
    def Uart_SendString(self, value): 
        self.serial.write(value)
  

    def Uart_ReceiveByte(self): 
        return self.serial.read(1)

    def Uart_ReceiveString(self, value): 
        data = self.serial.read(value)
        return data
        
    def Uart_Set_Baudrate(self, Baudrate):
         self.serial = serial.Serial("/dev/ttyS0",Baudrate)

    
    
    
