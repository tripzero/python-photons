import trollius as asyncio
from lightclient import LightProtocol
from binascii import hexlify
from wss.wssserver import Server, server_main
from collections import deque

class LightServerWss(Server):
	def __init__(self, leds=None, port=None, iface = "localhost", useSsl=False, sslCert = "server.crt", sslKey = "server.key"):
		self.leds = leds
		self.port = port
		self.iface = iface

		#Keep about 5 seconds worth of data
		self.queue = deque([], self.leds.fps * 5)

		self.parser = LightProtocol(self.leds)

		Server.__init__(self, port = port, useSsl=useSsl, sslCert=sslCert, sslKey=sslKey)

		asyncio.get_event_loop().create_task(self._processQueue())

	def onBinaryMessage(self, msg, fromClient):
		data = bytearray()
		data.extend(msg)
		self.print_debug("can_has_data!!!")
		self.print_debug("length: {}".format(len(data)))
		self.print_debug("data: {}".format(hexlify(data)))

		self.queue.append(data)

	@asyncio.coroutine
	def _processQueue(self):
		while True:
			if len(self.queue):
				data = self.queue.popleft()
				self.parser.parse(data)

			yield asyncio.From(asyncio.sleep(1/self.leds.fps))


class LightServer():

	def __init__(self, leds, port, iface = "localhost", debug=False):

		self.leds = leds
		self.port = port
		self.iface = iface
		self.debug = debug

		loop = asyncio.get_event_loop()

		factory = asyncio.start_server(self.new_connection, host = iface, port = port)
		self.server = loop.run_until_complete(factory)

		self.parser = LightProtocol(self.leds)

		self.client_reader = None

	def print_debug(self, msg):
		if self.debug:
			print(msg)

	def new_connection(self, client_reader, client_writer):
		#we may have only one client
		try:
			self.print_debug("new connection!")

			self.client_reader = client_reader

			while True:

				self.print_debug("reading data...")
				data = yield asyncio.From(self.client_reader.read())

				if data:
					buff = bytearray()
					buff.extend(data)
					self.print_debug("can_has_data!!!")
					self.print_debug("length: {}".format(len(data)))
					self.print_debug("data: {}".format(hexlify(data)))
					self.parser.parse(buff)

				else:
					return

		except:
			import traceback, sys
			exc_type, exc_value, exc_traceback = sys.exc_info()
			traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
			traceback.print_exception(exc_type, exc_value, exc_traceback,
	                      limit=8, file=sys.stdout)

	def close():
		self.server.close()
		asyncio.get_event_loop().run_until_complete(self.server.wait_closed())



if __name__ == "__main__":
	from lights import LightArray2, OpenCvSimpleDriver, DummyDriver
	
	num_lights = 200

	leds = LightArray2(num_lights, DummyDriver(), fps=60)
	server = server_main(ServerClass=LightServerWss, leds=leds)

	server.start()

	asyncio.get_event_loop().run_forever()

	server.close()
