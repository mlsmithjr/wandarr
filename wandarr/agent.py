import socket
import os
import subprocess
import time
from threading import Thread
from typing import List


class Runner(Thread):
    def __init__(self, c, addr, thread_id: int):
        super().__init__(name=f"Runner {thread_id}", daemon=True)
        self.c = c
        self.addr = addr
        self.thread_id = thread_id

    def run(self):
        c = self.c
        try:
            has_sharing = False
            keep_source = False
            shared_in_path = None
            shared_out_path = None


            print(f'[{self.thread_id}]: got connection from addr', self.addr)
            hello = c.recv(2048).decode()
            print(f"[{self.thread_id}]", hello)
            if hello.startswith("PING"):
                c.send(bytes("PONG".encode()))
                c.close()
                return

            cli_parts = []
            if hello.startswith("HELLO|") | hello.startswith("HELLOS|"):
                parts = hello.split("|")
                if parts[0] == "HELLO":
                    # expect to receive the file
                    if len(parts) < 5:
                        print(f"[{self.thread_id}] Not enough values in HELLO packet: " + hello)
                        c.close()
                        return

                    filesize = int(parts[1])
                    tempdir = parts[2]
                    filename = parts[3]
                    cli = parts[4]
                    tmp_filename = os.path.join(tempdir, filename + ".tmp")

                    print(f"[{self.thread_id}] echoing back hello")
                    c.send(bytes(hello.encode()))

                    output_filename = self.receive_file(filesize, tempdir, filename, c)

                    cli = cli.replace(r"{FILENAME}", output_filename)
                    cli_parts = cli.split(r"$")
                    cli_parts.append(tmp_filename)

                elif parts[0] == "HELLOS":
                    has_sharing = True
                    # just use the passed-in cli since the host has access to the file via mapping
                    shared_in_path = parts[1]
                    shared_out_path = parts[2]
                    cli = parts[3]
                    keep_source = parts[4] == '1'
                    cli_parts = cli.split(r"$")

                #
                # start ffmpeg and pipe output back to wandarr controller for monitoring
                #
                print(f"[{self.thread_id}] receive complete - executing " + " ".join(cli_parts))
                vetoed = False
                with subprocess.Popen(cli_parts,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT,
                                      universal_newlines=True,
                                      shell=False) as proc:
                    while proc.poll() is None:
                        line = proc.stdout.readline()
                        if "video:" in line:
                            print("video: trigger detected")
                            # transcode complete
                            break

                        c.send(bytes(line.encode()))

                        response = c.recv(20)
                        confirmation = response.decode()
                        if confirmation == "PING":
                            # ping received out of context, ignore
                            continue
                        elif confirmation == "STOP":
                            proc.kill()
                            print(f"[{self.thread_id}] Client stopped the transcode, cleaning up")
                            vetoed = True
                            break
                        elif confirmation == "VETO":
                            proc.kill()
                            print(f"[{self.thread_id}] Client vetoed the transcode, cleaning up")
                            vetoed = True
                            break
                        elif confirmation != "ACK!":
                            proc.kill()
                            print(f"[{self.thread_id}] Protocol error - expected ACK from client, got {confirmation}")
                            print("Cleaning up")
                            vetoed = True
                            break

                    # wait for process to end
                    while proc.poll() is None:
                        time.sleep(1)

                    if not vetoed:
                        if proc.returncode != 0:
                            print(f"[{self.thread_id}] Error returned from ffmpeg. Try running manually to troubleshoot")
                            c.send(bytes(f"ERR|{proc.returncode}".encode()))
                            print(f"[{self.thread_id}] Cleaning up")
                        else:
                            print(f"[{self.thread_id}] > DONE")
                            # send the results back to the client
                            filesize = os.path.getsize(tmp_filename)
                            c.send(bytes(f"DONE|{proc.returncode}|{filesize}".encode()))
                            response = c.recv(4).decode()

                            if not has_sharing:
                                if response == "ACK!":
                                    # send the file back
                                    print(f"[{self.thread_id}] sending transcoded file")
                                    with open(tmp_filename, "rb") as input_file:
                                        blk = input_file.read(100_000)
                                        while len(blk) > 0:
                                            c.send(blk)
                                            blk = input_file.read(100_000)
                                    print(f"[{self.thread_id}] done")
                                else:
                                    print(f"[{self.thread_id}] expected ACK, got {response}")
                            else:
                                # file is on a share, so just rename in place
                                if not keep_source:
                                    os.remove(shared_in_path)
                                    os.rename(shared_out_path, shared_in_path)
                    else:
                        print(f"[{self.thread_id}] veto")

                    if not has_sharing:
                        os.remove(tmp_filename)
                        os.remove(output_filename)

        except Exception as ex:
            print(str(ex))

        c.close()

    def receive_file(self, filesize: int, tempdir: str, filename: str, c) -> str:

        print(f"[{self.thread_id}] receiving {filesize} bytes to {filename}...")
        output_filename = os.path.join(tempdir, filename)

        with open(output_filename, "wb") as f:
            while filesize > 0:
                chunk = c.recv(min(4096, filesize))
                if len(chunk) == 0:
                    break
                filesize -= len(chunk)
                f.write(chunk)
        return output_filename


class Agent:
    PORT = 9567

    def serve(self):
        s = socket.socket()
        s.bind(("", self.PORT))
        s.listen(10)
        thread_count = 1

        while True:
            print(f"listening on port {self.PORT}...")
            c, addr = s.accept()
            print(f"thread {thread_count} start")
            Runner(c, addr, thread_count).start()
            thread_count += 1
