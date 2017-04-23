#/usr/bin/env python

import numpy as np
from gi.repository import GObject
import trollius as asyncio
import copy
import math

class Id:
	id = None
	staticId = 0
	def __init__(self):
		self.id = Id.staticId
		Id.staticId += 1

class Promise:
	
	def __init__(self):
		self.success = None
		self.args = []
		self.promise = None

	def then(self, successCb, *args):

		self.success = successCb

		if len(args) > 0:
			self.args = args

		if not self.promise:
			self.promise = Promise()
		
		return self.promise

	def call(self):
		ret = None
		if self.success == None:
			return

		if len(self.args):
			ret = self.success(*self.args)
		else:
			ret = self.success()

		if ret and isinstance(ret, Promise) and self.promise:
			#print("promise future returned a promise.  Auto-attaching to chain")
			ret.then(self.promise.call)
		elif self.promise:
			#print("promise future return value not a promise")
			self.promise.call()


class Chase(Id):
	steps = 0
	step = 0
	led = 0
	color = (0,0,0)
	forward = True
	promise = None
	prevColor = (0,0,0)

	def __init__(self, color, steps):
		Id.__init__(self)
		self.color = color
		self.steps = steps
		self.promise = Promise()

	def complete(self):
		self.promise.call()

class ColorTransform(Id):

	def __init__(self, led, targetColor, startColor, redStep, blueStep, greenStep, num_frames):
		Id.__init__(self)
		self.startColor = (startColor[0], startColor[1], startColor[2])
		self.led = led
		self.targetColor = targetColor
		self.redStep = redStep
		self.greenStep = greenStep
		self.blueStep = blueStep
		self.steps = [self.redStep, self.greenStep, self.blueStep]
		self.frame_index = 0
		self.num_frames=num_frames
		self.color = startColor
		
		self.promise = Promise()

	def complete(self):
		self.promise.call()

class TransformToColor(Id):

	def __init__(self, led, targetColor):
		Id.__init__(self)
		self.led = led
		self.targetColor = targetColor
		
		self.promise = Promise()

	def complete(self):
		self.promise.call()

class AnimationFunc:

	def __init__(self, func, args):
		self.func = func
		self.args = args

class BaseAnimation:

	def __init__(self):
		self.animations = []
		self.promise = Promise()

	def addAnimation(self, animation, *args):
		if len(args) == 0:
			args = None

		self.animations.append(AnimationFunc(animation, args))

	def _do(self, animation):
		methodCall = animation.func
		args = animation.args

		if not methodCall:
			raise Exception("animation is not a method")

		if isinstance(methodCall, BaseAnimation):
			methodCall = methodCall.start

		if not args:
			return methodCall()
		else:
			return methodCall(*args)

class SequentialAnimation(BaseAnimation):

	def __init__(self):
		BaseAnimation.__init__(self)

	def start(self):
		if len(self.animations) == 0:
			self.promise.call()
		animation = self.animations.pop(0)
		self._do(animation).then(self._animationComplete)
		return self.promise

	def _animationComplete(self):
		if len(self.animations) == 0:
			self.promise.call()
			return

		animation = self.animations.pop(0)
		self._do(animation).then(self._animationComplete)

class ConcurrentAnimation(BaseAnimation):

	def __init__(self):
		BaseAnimation.__init__(self)

	def start(self):
		for animation in self.animations:
			self._do(animation).then(self._animationComplete, animation)

		return self.promise

	def _animationComplete(self, animation):
		self.animations.remove(animation)

		if len(self.animations) == 0:
			self.promise.call()

class Delay(BaseAnimation):
	def __init__(self, time):
		BaseAnimation.__init__(self)
		#time in miliseconds:
		self.time = time

	@asyncio.coroutine
	def do_sleep(self):
		yield asyncio.From(asyncio.sleep(self.time / 1000.0))
		self.promise.call()

	def start(self):
		asyncio.get_event_loop().create_task(self.do_sleep())
		
		return self.promise

		
class ColorTransformAnimation(BaseAnimation):
	def __init__(self, leds, debug=False):
		BaseAnimation.__init__(self)
		self.leds = leds
		self.animations = []
		self.debug=debug

	def addAnimation(self, led, color, time, fromColor = None):
		if not fromColor:
			prevColor = self.leds.color(led)[:]
		else:
			prevColor = fromColor

		
		redDelta = color[0] - prevColor[0]
		greenDelta = color[1] - prevColor[1]
		blueDelta = color[2] - prevColor[2]
		numFrames = self.leds.fps * (time / 1000.0)


		if numFrames < 1.0:
			numFrames = 1.0


		redSteps = redDelta / numFrames
		greenSteps = greenDelta / numFrames
		blueSteps = blueDelta / numFrames

		if self.debug:
			print("color = {}, target = {}".format(prevColor, color))
			print("num frames = {}".format(numFrames))
			print("redSteps = {}".format(redSteps))	

		if redSteps == 0 and color[0] != prevColor[0]:
			redSteps = 1
		if greenSteps == 0 and color[1] != prevColor[1]:
			greenSteps = 1
		if blueSteps == 0 and color[2] != prevColor[2]:
			blueSteps = 1


		t = ColorTransform(led, color[:], prevColor, redSteps, blueSteps, greenSteps, math.floor(numFrames))
		self.animations.append(t)

	def start(self):
		#print("animation {} started".format(self))
		asyncio.get_event_loop().create_task(self._run())

		return self.promise

	def change_color(self, animation):
		color = animation.color

		steps = animation.steps

		ret = False

		for c in xrange(3):
			s = steps[c]
			color[c] += s

		animation.frame_index += 1

		if animation.frame_index >= animation.num_frames:
			color = animation.targetColor
			ret = True
			animation.complete()

		animation.color = color
		self.leds.changeColor(animation.led, animation.color)

		if self.debug:
			print("led = {}, color = {}. target = {}".format(animation.led, color, animation.targetColor))
			print("start color: {}".format(animation.startColor))
			print("steps: {}".format(steps))
			print("{}/{} complete".format(animation.frame_index, animation.num_frames))

		return ret

	@asyncio.coroutine
	def _run(self):
		#print("trying to run animation for {}".format(self))
		try: 
			done_count = 0
			while done_count < len(self.animations):
				#print ("num animations left: {}".format(len(self.animations)))

				remove_list = []

				for animation in self.animations:
					if self.change_color(animation):
						#remove_list.append(animation)
						done_count += 1

				#print("remove_list = {}".format(len(remove_list)))
				#for remove in remove_list:
				#	self.animations.remove(remove)

				#print("yielding")
				yield asyncio.From(asyncio.sleep(1.0/self.leds.fps))
		except:
			print("error in animation loop for {}".format(self))
			import sys, traceback
			exc_type, exc_value, exc_traceback = sys.exc_info()
			traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
			traceback.print_exception(exc_type, exc_value, exc_traceback, limit=6, file=sys.stdout)

		if self.debug:
			print("animation {} is complete. Calling promise".format(self))

		self.promise.call()



class LightArray:
	ledArraySize = 0
	ledsData = None
	needsUpdate = False
	fps = 30
	driver = None

	def __init__(self, ledArraySize, driver, fps=30):
		self.setLedArraySize(ledArraySize)
		self.driver = driver
		self.fps = 30

	def setLedArraySize(self, ledArraySize):
		self.ledArraySize = ledArraySize
		self.ledsData = np.zeros((ledArraySize, 3), np.uint8)

	def clear(self):
		self.ledsData[:] = [0,0,0]
		self.update()

	def update(self):
		if self.needsUpdate == False:
			GObject.timeout_add(1000/self.fps, self._doUpdate)
		self.needsUpdate = True

	def _doUpdate(self):
		if self.needsUpdate == True:
			self.driver.update(self.ledsData)
			self.needsUpdate = False
		return False

	def changeColor(self, ledNumber, color):
		self.ledsData[ledNumber] = color
		self.update()

	def chase(self, color, time, delay):
		steps = time / delay
		c = Chase(color, steps)
		GObject.timeout_add(delay, self._doChase, c)
		return c.promise

	def _doChase(self, c):
		if c.step >= c.steps:
			c.promise.call()
			return False
		if c.led >= self.ledArraySize:
			c.forward = False
		if c.led <= 0:
			c.forward = True
		#restore previous led color
		self.changeColor(c.led, c.prevColor)

		if c.forward == True:
			c.led += 1
		else:
			c.led -= 1

		c.prevColor = self.ledsData[c.led]

		self.changeColor(c.led, c.color)
		c.step += 1

		return True

	def transformColorTo(self, led, color, time):
		prevColor = self.ledsData[led]
		steps = [color[0] - prevColor[0], color[1] - prevColor[1], color[2] - prevColor[2]]
		stepsAbs = [abs(steps[0]), abs(steps[1]), abs(steps[2]), 1]
		maxSteps = max(1, stepsAbs)
		delay = time / maxSteps
		t = TransformToColor(led, color)
		GObject.timeout_add(delay, self._doTransformColorTo, t)
		return t.promise

	def _doTransformColorTo(self, transform):
		stillTransforming = False
		color = self.ledsData[transform.led]
		for i in range(3):
			if color[i] < transform.targetColor[i]:
				color[i] += 1
				stillTransforming = True
			elif color[i] > transform.targetColor[i]:
				color[i] -= 1
				stillTransforming = True
		self.ledsData[transform.led] = color
		self.update()
		if stillTransforming == False:
			transform.complete()
		return stillTransforming

class LightFpsController:


	def __init__(self, driver, fps=30, loop=asyncio.get_event_loop()):
		self.driver = driver
		self.loop = loop
		self.fps = fps
		self.needsUpdate = False
		self.loop.create_task(self._updateLoop())


	def update(self, data=None):
		if data is not None:
			self.ledsData = data

		self.needsUpdate = True

	def updateNow(self):
		self.driver.update(self.ledsData)

	@asyncio.coroutine
	def _updateLoop(self):
		while True:
			try:
				if self.needsUpdate == True:
					self.updateNow()
					self.needsUpdate = False
			except:
				print("bork in _doUpdate")
				import traceback, sys
				exc_type, exc_value, exc_traceback = sys.exc_info()
				traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
				traceback.print_exception(exc_type, exc_value, exc_traceback,
	                          limit=8, file=sys.stdout)
			yield asyncio.From(asyncio.sleep(1.0 / self.fps))

class LightArray2(LightFpsController):
	ledArraySize = 0
	ledsData = None
	needsUpdate = False
	driver = None

	def __init__(self, ledArraySize, driver, fps=30, loop=asyncio.get_event_loop()):
		LightFpsController.__init__(self, driver, fps, loop)
		self.setLedArraySize(ledArraySize)

		import threading

		self.locker = threading.Lock()

	def setLedArraySize(self, ledArraySize):
		self.ledArraySize = ledArraySize
		self.ledsData = np.zeros((ledArraySize, 3), np.uint8)

	def clear(self):
		self.ledsData[:] = (0,0,0)
		self.update()

	def changeColor(self, ledNumber, color):
		with self.locker:
			self.ledsData[ledNumber] = color
			self.update()

	def color(self, ledNumber):
		with self.locker:
			return self.ledsData[ledNumber]

	def pushFront(self, colors):
		if isinstance(colors[0], tuple):
			l = len(colors)
			lm = -1 * l
			self.ledsData[l:] = self.ledsData[:lm]
			self.ledsData[0:l] = colors
		else:
			self.pushFront([colors])

			self.update()

	def pushBack(self, colors):
		if isinstance(colors[0], tuple):
			l = len(colors)
			lm = -1 * l
			end = len(self.ledsData) - l
			self.ledsData[:lm] = self.ledsData[l:]
			self.ledsData[lm:] = colors
		else:
			self.pushBack([colors])

			self.update()


	def transformColorTo(self, led, color, time):
		prevColor = self.ledsData[led]
		redSteps = abs(prevColor[0] - color[0])
		greenSteps = abs(prevColor[1] - color[1])
		blueSteps = abs(prevColor[2] - color[2])
		numFrames = int(self.fps * (time / 1000.0))

		redSteps = redSteps / numFrames
		blueSteps = blueSteps / numFrames
		greenSteps = greenSteps / numFrames

		t = TransformToColor(led, color)
		self.loop.create_task(self._doTransformColorTo(t, redSteps, greenSteps, blueSteps, numFrames))
		return t.promise

	@asyncio.coroutine
	def _doTransformColorTo(self, transform, redSteps, greenSteps, blueSteps, numFrames):
		color = self.ledsData[transform.led]

		steps = [redSteps, greenSteps, blueSteps]

		for i in xrange(numFrames):
			for c in xrange(3):
				if color[c] < transform.targetColor[c]:
					color[c] += steps[c]
				elif color[c] > transform.targetColor[c]:
					color[c] -= steps[c]

			self.changeColor(transform.led, color)

			yield asyncio.From(asyncio.sleep(1.0/self.fps))

		transform.complete()


class Ws2801Driver:
	spiDev = None

	def __init__(self, debug=None):
		import mraa
		self.spiDev = mraa.Spi(0)

	def update(self, ledsData):
		self.spiDev.write(bytearray(np.getbuffer(ledsData)))

class PixelFormat:
	gbr =	[1, 2, 0]
	bgr = [2, 1, 0]
	rbg = [0, 2, 1]


class Apa102Driver:

	def __init__(self, freqs=1000000, debug=None, brightness=100, pixel_order=PixelFormat.gbr):
		import mraa
		self.spiDev = mraa.Spi(0)
		self.spiDev.frequency(freqs)
		self.brightness = brightness

		"""
		Set the color order of the lights.  This is used to convert
		RGB (the default format) to the right physical colors on the 
		light.
		"""
		self.pixel_order = pixel_order

	def setGlobalBrightness(self, brightness):
		if brightness >= 0 and brightness <= 100:
			self.brightness = brightness
		else:
			print("brightness is out of range (0-100)")

	def _calcGlobalBrightness(self, brightness):
		brightness = 31 * 0.01 * brightness
		brightness = int(brightness)
		msb = 0b11100000
		if brightness > 31:
			brightness = 31

		return msb | brightness

	def power(self, ledsData):
		return np.sum((ledsData / (255, 255, 255) * 0.2))

	def update(self, ledsData):
		data = bytearray()
		data[:4] = [0x00, 0x00, 0x00, 0x00]
		po = self.pixel_order
		for rgb in ledsData:
			data.append(self._calcGlobalBrightness(self.brightness))
			# write pixel data
			data.extend([rgb[po[0]], rgb[po[1]], rgb[po[2]]])

		#endframe
		data.extend([0xff, 0xff, 0xff, 0xff])

		self.spiDev.write(data)


class OpenCvSimpleDriver:
	

	def __init__(self, debug=None, size=50, wrap=100, opengl=False):
		self.debug=debug
		self.image = None
		self.size = size
		self.wrap = wrap
		
		print("using size: {}".format(self.size))

		import cv2

		self.imshow = cv2.imshow
		self.waitKey = cv2.waitKey

		if opengl:
			cv2.namedWindow("output", cv2.WINDOW_OPENGL)

	def update(self, ledsData):
		width = len(ledsData) * self.size
		height = self.size

		if len(ledsData) > self.wrap:
			width = self.wrap * self.size
			height = self.size * len(ledsData) / self.wrap


		if not isinstance(self.image, list):
			self.image = np.zeros((height, width, 3), np.uint8)
			self.imshow("output", self.image)
			self.waitKey(1)

		x = 0
		i = 0
		y = 0

		for color in ledsData:
			self.image[y : y + self.size, x : x + self.size] = color[::-1]
			x += self.size
			i += 1
			if i > self.wrap:
				y += self.size
				x = 0
				i = 0

		self.imshow("output", self.image)
		self.waitKey(1)


class OpenCvDriver:
	image = None
	size = 50
	dimensions = None

	def __init__(self, debug=None):
		self.dimensions = (1, 1, 0, 0)

	def update(self, ledsData):
		import cv2

		bottom, right, top, left = self.dimensions
		height = max(right, left, 1)
		width = max(bottom, top, 1)
		if width == 1 and right and left:
			width = 2

		if height == 1 and bottom and top:
			height = 2

		width = width * self.size
		height = height * self.size

		if self.image == None:
			self.image = np.zeros((height, width, 3), np.uint8)

		yStep = height / 8
		xStep = width / 8

		if right != 0:
			yStep = height / (right)
		if bottom != 0:
			xStep = width / (bottom)

		#bottom
		y = height
		x = 0

		if bottom:
			pos = 0
			posEnd = bottom
			for color in ledsData[pos : posEnd]:
				self.image[height - self.size : height, x : x + xStep] = color
				x += xStep

		#right
		if right:
			pos = bottom
			posEnd = pos + right
			for color in ledsData[pos : posEnd]:
				self.image[y - yStep : y, width - self.size : width] = color
				y -= yStep

		#reset steps for top and left
		yStep = height / 8
		xStep = width / 8

		if left != 0:
			yStep = height / (left)
		if top != 0:
			xStep = width / (top)

		x = width

		#top
		if top:
			pos = bottom + right
			posEnd = pos + top
			for color in ledsData[pos : posEnd]:
				self.image[0 : self.size, x - xStep : x] = color
				x -= xStep

		y = 0

		#left
		if left:
			pos = bottom + right + top
			posEnd = pos + left
			for color in ledsData[pos : posEnd]:
				self.image[y : y + yStep, 0 : self.size] = color
				y += yStep

		cv2.imshow("output", self.image)

class DummyDriver:

	def __init__(self, debug=None, **kwargs):
		pass

	def update(self, ledsData):
		pass

def getDriver(driverName = None):
	try:
		from lights.lightclient import LightClient
	except ImportError:
		from lightclient import LightClient

	drivers = { "Ws2801" : Ws2801Driver, "Apa102" : Apa102Driver, "OpenCV" : OpenCvDriver, "LightProtocol" : LightClient, 
				"OpenCVSimple" : OpenCvSimpleDriver, "Dummy" : DummyDriver }

	if driverName and driverName in drivers:
		return drivers[driverName]

	print("driver {} not supported".format(driverName))
	print("supported drivers:")

	for driver in drivers.keys():
		print("\t{}".format(driver))

	return None
