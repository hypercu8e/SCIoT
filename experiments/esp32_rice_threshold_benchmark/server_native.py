"""Same server/protocol, with a native Rice hot path; audit stays pure Python."""
from native_decoder import NativeRice
import protocol
from server import main
native=NativeRice()
protocol.rice_decode=native.decode
BaseDecoder=protocol.Decoder
class NativeDecoder(BaseDecoder):
    def decode(self,body):
        row=super().decode(body)
        row['rice_decoder_backend']='native'
        return row
# server imported Decoder before this substitution; replace its local binding too.
import server
server.Decoder=NativeDecoder
if __name__=='__main__':main()
