import socket
import os
import subprocess
import time
from threading import Thread


class Runner(Thread):
    def __init__(self, c, addr, thread_id: int):
        super().__init__(name=f"Runner {thread_id}", daemon=True)
        self.c = c
        self.addr = addr
        self.thread_id = thread_id

    def run(self):
        c = self.c
        try:
            print(f'[{self.thread_id}]: got connection from addr', self.addr)
            hello = c.recv(2048).decode()
            print(f"[{self.thread_id}]", hello)
            if hello.startswith("PING"):
                c.send(bytes("PONG".encode()))
                c.close()
                return

            if hello.startswith("HELLO|"):

                parts = hello.split("|")
                if len(parts) < 5:
                    print(f"[{self.thread_id}] Not enough values in HELLO packet: " + hello)
                    c.close()
                    return

                filesize = int(parts[1])
                tempdir = parts[2]
                filename = parts[3]
                cli = parts[4]

                print(f"[{self.thread_id}] echoing back hello")
                c.send(bytes(hello.encode()))

                print(f"[{self.thread_id}] receiving {filesize} bytes to {filename}...")
                output_filename = os.path.join(tempdir, filename)
                tmp_filename = os.path.join(tempdir, filename + ".tmp")

                with open(output_filename, "wb") as f:
                    while filesize > 0:
                        chunk = c.recv(min(4096, filesize))
                        if len(chunk) == 0:
                            break
                        filesize -= len(chunk)
                        f.write(chunk)

                cli = cli.replace(r"{FILENAME}", output_filename)
                cli_parts = cli.split(r"$")
                print(f"[{self.thread_id}] receive complete - executing " + " ".join(cli_parts))
                cli_parts.append(tmp_filename)

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
                            print(f"[{self.thread_id}] > ERR")
                            c.send(bytes(f"ERR|{proc.returncode}".encode()))
                            print(f"[{self.thread_id}] Cleaning up")
                        else:
                            print(f"[{self.thread_id}] > DONE")
                            filesize = os.path.getsize(tmp_filename)
                            c.send(bytes(f"DONE|{proc.returncode}|{filesize}".encode()))
                            # wait for response, then send file
                            response = c.recv(4).decode()
                            if response == "ACK!":
                                # send the file back
                                print(f"[{self.thread_id}] sending transcoded file")
                                with open(tmp_filename, "rb") as input_file:
                                    blk = input_file.read(1_000_000)
                                    while len(blk) > 0:
                                        c.send(blk)
                                        blk = input_file.read(1_000_000)
                                print(f"[{self.thread_id}] done")
                            else:
                                print(f"[{self.thread_id}] expected ACK, got {response}")
                    else:
                        print(f"[{self.thread_id}] veto")

                    os.remove(tmp_filename)
                    os.remove(output_filename)

        except Exception as ex:
            print(str(ex))

        c.close()


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
