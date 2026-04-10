
import abc
from typing import Iterator, Tuple

class FirmwareFile(abc.ABC):
    @staticmethod
    def from_file(file):
        return _FsFirmwareFile(file)

    @abc.abstractmethod
    def as_buffer(self) -> bytes:
        """
        Returns the contents of the file as byte array.
        """
        pass

    @abc.abstractmethod
    def as_stream(self):
        """
        Returns a context manager that provides a stream of the file content
        """
        pass

    @abc.abstractmethod
    def as_file(self):
        """
        Returns a context manager that provides an object with a `name`
        attribute that points to an actual file in the filesystem.
        """
        pass
    
    def get_flash_sections(self) -> Iterator[Tuple[str, int, bytes]]:
        """
        Scans the ELF file for sections to be loaded and returns them as an
        iterator of tuples (name: str, addr: int, content: bytes).
        """
        import elftools.elf.elffile
        
        with self.as_stream() as stream:
            elffile = elftools.elf.elffile.ELFFile(stream)
            for segment in elffile.iter_segments():
                if segment.header['p_type'] != 'PT_LOAD':
                    continue # skip no-load sections
                #print(segment.header)

                segment_vaddr = segment.header['p_vaddr']
                segment_addr = segment.header['p_paddr']
                segment_size = segment.header['p_filesz']

                for section in elffile.iter_sections():
                    if segment.section_in_segment(section):
                        section_addr = section.header['sh_addr'] - segment_vaddr + segment_addr # convert virt addr to phys addr
                        section_size = section.header['sh_size']

                        # Prune the section based on the containing segment's range.
                        # For instance the .bss section has a non-zero size even
                        # though it's in a segment with p_filesz==0.
                        if section_addr < segment_addr:
                            section_size -= segment_addr - section_addr # can get <0
                            section_addr = segment_addr
                        if section_addr + section_size > segment_addr + segment_size:
                            section_size = segment_addr + segment_size - section_addr
                        
                        if section_size <= 0:
                            continue # skip sections with zero bytes to load

                        yield section.name, section_addr, section.data()

    def get_reset_address(self):
        """Returns the reset address for this firmware."""
        import elftools.elf.elffile
        
        with self.as_stream() as stream:
            elffile = elftools.elf.elffile.ELFFile(stream)
            isr_vector_section = [
                s for s in elffile.iter_sections()
                if s.name == '.isr_vector'][0]
            return isr_vector_section.header['sh_addr']

class _FsFirmwareFile(FirmwareFile):
    def __init__(self, path: str):
        self.name = path

    def as_buffer(self):
        with self.as_stream() as stream:
            return stream.read()

    def as_stream(self):
        return open(self.name, 'rb')

    def as_file(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
