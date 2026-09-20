/*
* Sketch for SAM "Patsiuk" project
* Fully written by Vitalii Kuzhdin (@vitaliikuzhdin), vitaliikuzhdin@gmail.com
* For more information, look at shematic
*/

/*=============SETTINGS=============*/
#define RIDING_TIME           240    // ms, must be 10 cm
#define TURNING_TIME          1200   // ms, must be 90 degrees
#define MIN_DUTY              0    // motors should start at this speed (1-255)
#define SMOOTH_SPEED          50     // ms, time for motors to reach the speed
#define MAX_SPEED             255    // max motor speed (1-255)
#define OBSTACLE_CM           11     // anything closer than this counts as blocking
#define SONAR_SAMPLES         5      // pings averaged per obstacle check
#define SONAR_MAX_CM          200    // NewPing range limit (the library caps at 500)
#define METAL_MARGIN          8      // ADC counts above the idle baseline that is a find
#define RIGHT_FRONT_DIRECTION NORMAL // motor direcion, NORMAL or REVERSE
#define RIGHT_BACK_DIRECTION  NORMAL // motor direcion, NORMAL or REVERSE
#define LEFT_FRONT_DIRECTION  NORMAL // motor direcion, NORMAL or REVERSE
#define LEFT_BACK_DIRECTION   NORMAL // motor direcion, NORMAL or REVERSE
#define RIGHT_FRONT_MODE      HIGH   // change if motor is "on brake" (HIGH or LOW)
#define RIGHT_BACK_MODE       HIGH   // change if motor is "on brake" (HIGH or LOW)
#define LEFT_FRONT_MODE       HIGH   // change if motor is "on brake" (HIGH or LOW)
#define LEFT_BACK_MODE        HIGH   // change if motor is "on brake" (HIGH or LOW)

/*==========PINS==========*/
#define RIGHT_FRONT_PWM   3
#define RIGHT_FRONT_D	    2

#define RIGHT_BACK_PWM	  10
#define RIGHT_BACK_D 	    A3

#define LEFT_FRONT_PWM 	  9
#define LEFT_FRONT_D 	    4

#define LEFT_BACK_PWM 	  11
#define LEFT_BACK_D 	    A4

#define RIGHT_TRIG 		    6
#define RIGHT_ECHO 		    7
#define RIGHT_SONAR_VCC	  5

#define LEFT_TRIG 		    13
#define LEFT_ECHO 		    12
#define LEFT_SONAR_VCC 	  8

#define METAL_PIN 		    A5

/*=================MESSAGES=================*/
const char FOUND_MSG[] PROGMEM = {'Y'};
const char NOT_FOUND_MSG[] PROGMEM = {'n'};
const char DONE_RIDING_MSG[] PROGMEM = {'e'};

/*===================================LIBRARIES===================================*/
#include <NewPing.h> 	// documentation: bitbucket.org/teckel12/arduino-new-ping/wiki/Home
NewPing RIGHT_SONAR(RIGHT_TRIG, RIGHT_ECHO, SONAR_MAX_CM);
NewPing LEFT_SONAR(LEFT_TRIG, LEFT_ECHO, SONAR_MAX_CM);

#include <GyverMotor.h>	// documentation: alexgyver.ru/gyvermotor
GMotor RIGHT_FRONT(DRIVER2WIRE, RIGHT_FRONT_D, RIGHT_FRONT_PWM, RIGHT_FRONT_MODE);
GMotor RIGHT_BACK(DRIVER2WIRE, RIGHT_BACK_D, RIGHT_BACK_PWM, RIGHT_BACK_MODE);
GMotor LEFT_FRONT(DRIVER2WIRE, LEFT_FRONT_D, LEFT_FRONT_PWM, LEFT_FRONT_MODE);
GMotor LEFT_BACK(DRIVER2WIRE, LEFT_BACK_D, LEFT_BACK_PWM, LEFT_BACK_MODE);

/*=============GLOBAL VARIABLES=============*/

// PARSING
bool doneParsing, startParsing, readMode;
String stringConvert;

// RIDING
bool joystickMode, stopCarBool;
int X, xDuplicate, Y;

// AVOIDING
byte timesAvoidedX, timesAvoidedY;
bool avoidedObstacles;

// RETURNING HOME
bool doneReturning;
int angle, xTravel, yTravel;

// METAL DETECTOR
unsigned int smallestMetal;

void setup(void) {
    Serial.begin(9600);

    // D9 and D10 31.4 kHz phase-corect PWM
    TCCR1A = 0b00000001;
    TCCR1B = 0b00000001;

    // D3 and D11 31.4 kHz phase-corect PWM
    TCCR2B = 0b00000001;
    TCCR2A = 0b00000001;

    pinMode(METAL_PIN, INPUT);

    pinMode(RIGHT_FRONT_D, OUTPUT);
    pinMode(RIGHT_FRONT_PWM, OUTPUT);

    pinMode(RIGHT_BACK_D, OUTPUT);
    pinMode(RIGHT_BACK_PWM, OUTPUT);

    pinMode(LEFT_FRONT_D, OUTPUT);
    pinMode(LEFT_FRONT_PWM, OUTPUT);

    pinMode(LEFT_BACK_D, OUTPUT);
    pinMode(LEFT_BACK_PWM, OUTPUT);

    pinMode(RIGHT_SONAR_VCC, OUTPUT);
    pinMode(LEFT_SONAR_VCC, OUTPUT);

    digitalWrite(RIGHT_SONAR_VCC, HIGH); // power for right sonar
    digitalWrite(LEFT_SONAR_VCC, HIGH);  // power for left  sonar

    RIGHT_FRONT.setResolution(8);
    RIGHT_BACK.setResolution(8);
    LEFT_FRONT.setResolution(8);
    LEFT_BACK.setResolution(8);

    RIGHT_FRONT.setDirection(RIGHT_FRONT_DIRECTION);
    RIGHT_BACK.setDirection(RIGHT_BACK_DIRECTION);
    LEFT_FRONT.setDirection(LEFT_FRONT_DIRECTION);
    LEFT_BACK.setDirection(LEFT_BACK_DIRECTION);

    RIGHT_FRONT.setMinDuty(MIN_DUTY);
    RIGHT_BACK.setMinDuty(MIN_DUTY);
    LEFT_FRONT.setMinDuty(MIN_DUTY);
    LEFT_BACK.setMinDuty(MIN_DUTY);

    RIGHT_FRONT.setMode(AUTO);
    RIGHT_BACK.setMode(AUTO);
    LEFT_FRONT.setMode(AUTO);
    LEFT_BACK.setMode(AUTO);

    RIGHT_FRONT.setSmoothSpeed(SMOOTH_SPEED);
    RIGHT_BACK.setSmoothSpeed(SMOOTH_SPEED);
    LEFT_FRONT.setSmoothSpeed(SMOOTH_SPEED);
    LEFT_BACK.setSmoothSpeed(SMOOTH_SPEED);

    delay(1000); // to charge capacitors on metal detector

    // Average the idle coil reading. A single sample can be an outlier and
    // every later find is judged against this baseline.
    unsigned long baseline = 0;
    for (byte i = 0; i < 16; i++) {
        baseline += readMetal();
        delay(5);
    }
    smallestMetal = baseline / 16;
}

void loop(void) {
    parsing();
	
    if (doneParsing) {
        Serial.println((char)pgm_read_byte(&NOT_FOUND_MSG));

        if (joystickMode) {
            joystickDuty();
			
        } else { // (joystickMode == false)
            if (stopCarBool == false) {
                if (noObstacles()) {
                    if (avoidedObstacles == false) {
                        if (Y > 0) {
                            if (X > 0) {
                                if (timesAvoidedX == 0) {
                                    forward();
                                } else {
                                    timesAvoidedX--;  
                                }
                                X--;
                            } else { // (X == 0) change to the next lane
                                timesAvoidedX = 0;
                                if (Y % 2 == 0) { // Y is even
                                    right();
                                    forward();
                                    right();
                                } else { // (Y % 2 != 0) Y is odd
                                    left();
                                    forward();
                                    left();
                                }
                                X = xDuplicate;
                                Y--;
                            }
                        
                        } else { // (Y == 0) done riding, return home
                            if (doneReturning == false) {
                                returnHome();
                                Serial.println((char)pgm_read_byte(&DONE_RIDING_MSG));
                                stopCar();
                            }
                        }
                    } else { // (avoidedObstacles)
                        if (timesAvoidedY > 0) {
                            if (angle != 270) {
                                left();
                            } else {
                                forward();
                                timesAvoidedY--;
                            }
                        } else { // (timesAvoidedY == 0)
                            if (angle != 0) {
                                right();
                            } else {
                                avoidedObstacles = false;
                            }
                        }
                    }
                } else { // (noObstacles() == false)
                    right();
                    forward();
                    left();
                    timesAvoidedY++;
                }   
            } else { // (stopCarBool)
                stopCar();
                Serial.println((char)pgm_read_byte(&FOUND_MSG));
                doneParsing = false;  
            }
        }
		
        doneParsing = false;
    }
}

// Clears the dead-reckoning and avoidance state. Only at the start of a new
// auto run: doing it per packet would wipe the pose and unlatch a metal stop.
void startMission(void) {
    xTravel = 0;
    yTravel = 0;
    angle = 0;
    stopCarBool = false;
    doneReturning = false;
    avoidedObstacles = false;
    timesAvoidedX = 0;
    timesAvoidedY = 0;
}

void returnHome(void) {
    // return home Y
    if (yTravel > 0) {
        if (angle != 180) {
            right();
        } else {
            forward();  
        }
    }
    else if (yTravel < 0) {
        if (angle != 0) {
            right();
        } else {
            forward();
        }
    }
	
    // return home X
    else if (xTravel > 0) {
        if (angle != 270) {
            right();  
        } else {
            forward();
        }
    }
    else if (xTravel < 0) {
        if (angle != 90) {
            right();
        } else {
            forward();  
        }
    } else {
        doneReturning = true;
    }
}

// ping_cm() answers 0 when no echo comes back, which means "nothing in range",
// not "an obstacle at 0 cm". Averaging those zeroes in reads a clear path as a
// wall, so only real echoes are counted.
unsigned int distanceTo(NewPing &sonar) {
	// filter sonar analog noises
    unsigned int summ = 0;
    byte echoes = 0;
    for (byte i = 0; i < SONAR_SAMPLES; i++) {
        unsigned int cm = sonar.ping_cm();
        if (cm > 0) {
            summ += cm;
            echoes++;
        }
        delay(29);  // NewPing needs >= 29 ms between pings
    }
    return echoes ? summ / echoes : SONAR_MAX_CM;
}

bool noObstacles(void) {
    stopCar();
	
	return !(distanceTo(RIGHT_SONAR) <= OBSTACLE_CM or distanceTo(LEFT_SONAR) <= OBSTACLE_CM);
}

void right(void) {
    RIGHT_FRONT.setSpeed(-MAX_SPEED);
    RIGHT_BACK.setSpeed(-MAX_SPEED);
    LEFT_FRONT.setSpeed(MAX_SPEED);
    LEFT_BACK.setSpeed(MAX_SPEED);

    angle += 90;
    if (angle >= 360) {
        angle -= 360;
    }

    delay(TURNING_TIME);
}

void left(void) {
    RIGHT_FRONT.setSpeed(MAX_SPEED);
    RIGHT_BACK.setSpeed(MAX_SPEED);
    LEFT_FRONT.setSpeed(-MAX_SPEED);
    LEFT_BACK.setSpeed(-MAX_SPEED);

    angle -= 90;
    if (angle < 0) {
        angle += 360;
    }

    delay(TURNING_TIME);
}

void forward(void) {
    RIGHT_FRONT.setSpeed(MAX_SPEED);
    RIGHT_BACK.setSpeed(MAX_SPEED);
    LEFT_FRONT.setSpeed(MAX_SPEED);
    LEFT_BACK.setSpeed(MAX_SPEED);

    // One heading per case, or returnHome() cannot undo the travel it records.
    if (angle == 0) {
        yTravel++;
    } else if (angle == 90) {
        xTravel++;
    } else if (angle == 180) {
        yTravel--;
    } else { // (angle == 270)
        xTravel--;
    }

    for (unsigned int i = 0; i < RIDING_TIME; i++) {
        
        if (foundMetal()) {
            Serial.println((char)pgm_read_byte(&FOUND_MSG)); // Found!
            stopCarBool = true;
            stopCar();  // do not drive on over a find
            break;
        }

        delay(1);
    }
}

void stopCar(void) {
    RIGHT_FRONT.setSpeed(0);
    RIGHT_BACK.setSpeed(0);
    LEFT_FRONT.setSpeed(0);
    LEFT_BACK.setSpeed(0);
}

// analogRead() spans 0-1023, so this must not be a byte: truncating to 8 bits
// wraps the coil reading back to 0 every 256 counts.
unsigned int readMetal(){
	return analogRead(METAL_PIN);
}

bool foundMetal(void) {
	return readMetal() > smallestMetal + METAL_MARGIN;
}

void joystickDuty(void){
	  int dutyR = Y + X;
    int dutyL = Y - X;

    dutyR = constrain(dutyR, -MAX_SPEED, MAX_SPEED);
    dutyL = constrain(dutyL, -MAX_SPEED, MAX_SPEED);

    RIGHT_FRONT.smoothTick(dutyR);
    RIGHT_BACK.smoothTick(dutyR);
    LEFT_FRONT.smoothTick(dutyL);
    LEFT_BACK.smoothTick(dutyL);

	Serial.flush();
	if (foundMetal()) { 
        Serial.println((char)pgm_read_byte(&FOUND_MSG));
    } else { // (below the baseline + margin)
        Serial.println((char)pgm_read_byte(&NOT_FOUND_MSG));
    }
}

/*
* This function reads packets like this: $125,-28@1;
* where 125,-28 is X and Y accordingly
* 1 is mode (1 - joystick, 0 - auto)
*/
void parsing(void) {
    if (Serial.available() > 0) {
        doneParsing = false;
        char incomingChar = Serial.read();

        if (startParsing) {
            if (incomingChar == ',') {
                X = stringConvert.toInt();
                stringConvert = "";
            }
            else if (incomingChar == '@') {
                Y = stringConvert.toInt();
                stringConvert = "";
                startParsing = false;
                readMode = true;
            } else {
                stringConvert += incomingChar;
            }
        }

        else if (readMode) {
            readMode = false;
            joystickMode = incomingChar - '0';
            if (joystickMode == false) {
                X = X * 10 + 1;
                Y = Y * 10 + 1;
                xDuplicate = X;
                startMission();
            }
        }

        else if (incomingChar == '$') {
            startParsing = true;
        }
        else if (incomingChar == ';') {
            doneParsing = true;
        }
    }
}