"""TCP framing, per-connection state and end-to-end tensor reconstruction."""

import socket
import threading
import unittest

import numpy as np
from compare import HEADER
from lossy_codec import Session
from socket_benchmark import (
    LENGTH,
    MAX_MESSAGE,
    WireCodec,
    json_bytes,
    receive_message,
    replay,
    send_message,
    serve_connection,
)


class TransportTests(unittest.TestCase):
    def test_fragmented_messages_and_truncated_stream(self):
        sender, receiver = socket.socketpair()
        with sender, receiver:
            # recv must reassemble a message even across many short reads.
            data = LENGTH.pack(5) + b"hello"
            for byte in data:
                sender.sendall(bytes([byte]))
            self.assertEqual(receive_message(receiver), b"hello")
            sender.sendall(LENGTH.pack(5) + b"hi")
            sender.shutdown(socket.SHUT_WR)
            with self.assertRaises(EOFError):
                receive_message(receiver)

    def test_length_limit_rejected_before_payload_read(self):
        sender, receiver = socket.socketpair()
        with sender, receiver:
            sender.sendall(LENGTH.pack(MAX_MESSAGE + 1))
            with self.assertRaisesRegex(ValueError, "size limit"):
                receive_message(receiver)

    def test_server_rejects_wrong_model_before_acknowledgement(self):
        sender, receiver = socket.socketpair()
        session = Session((1024,), 0.001, "temporal", 25, "wrong", "cut")
        with sender, receiver:
            send_message(sender, json_bytes({
                "protocol": "activation-tcp-v1", "method": "temporal",
                "codec_session_hex": session.to_packet().hex(),
            }))
            with self.assertRaisesRegex(ValueError, "disagrees with server"):
                serve_connection(receiver, "expected", "cut", (1024,), lambda x: x)

    def test_sequence_and_corruption_do_not_advance_decoder(self):
        frame = np.arange(1024, dtype=np.float32)
        for method in ("raw", "independent", "temporal"):
            session = Session(frame.shape, 0.001,
                              "independent" if method == "raw" else method, 25)
            encoder, decoder = WireCodec(session, method), WireCodec(session, method)
            packet, _ = encoder.encode(frame)
            fields = list(HEADER.unpack_from(packet))
            fields[-1] ^= 1
            corrupted = HEADER.pack(*fields) + packet[HEADER.size:]
            with self.assertRaises(ValueError):
                decoder.decode(corrupted)
            self.assertEqual(decoder.received_sequence, -1)
            decoder.decode(packet)
            with self.assertRaisesRegex(ValueError, "Nonconsecutive"):
                decoder.decode(packet)

    def test_tcp_replay_all_modes_and_reconnect_isolates_reference(self):
        # A real loopback listener; fake suffix keeps this independent of TF.
        arrays = np.repeat(np.linspace(0, 1, 1024, dtype=np.float32)[None], 8, axis=0)
        metadata = {"model_sha256": "model", "split": {"layer": "cut"},
                    "preprocessing": {"sampling_fps": 5}}
        errors = []
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.settimeout(5)
        port = listener.getsockname()[1]

        def worker():
            try:
                for _ in range(6):
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(5)
                        serve_connection(connection, "model", "cut", (1024,),
                                         lambda x: np.array([x.sum()], dtype=np.float32))
            except (OSError, ValueError, EOFError, AssertionError) as error:
                errors.append(error)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        outputs = {}
        try:
            for method in ("raw", "independent", "temporal"):
                result, rows, outputs[method] = replay(
                    "127.0.0.1", port, arrays, metadata, method, 0.001, 4, timeout=5)
                self.assertEqual(result["connections"], 2)
                self.assertEqual([row["sequence"] for row in rows], [0, 1, 2, 3] * 2)
                self.assertNotEqual(rows[4]["kind"], 2)  # reconnect starts with full
                self.assertEqual(result["client_application_bytes"],
                                 result["handshake_client_bytes"]
                                 + sum(row["request_bytes"] for row in rows))
                self.assertEqual(result["server_application_bytes"],
                                 result["handshake_server_bytes"]
                                 + sum(row["response_bytes"] for row in rows))
                if method == "temporal":
                    self.assertEqual(result["selected_delta_frames"], 6)
            np.testing.assert_array_equal(outputs["independent"], outputs["temporal"])
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
