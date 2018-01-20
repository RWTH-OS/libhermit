#!/usr/bin/env python
"""Copyright (c) 2017, Annika Wierichs, RWTH Aachen University

All rights reserved.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
   * Redistributions of source code must retain the above copyright
     notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.
   * Neither the name of the University nor the names of its contributors
     may be used to endorse or promote products derived from this
     software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


This script expects a text file containing function prototypes as input
(SRC_PATH). It generates the following C code snippets for each individual given
function in the input file. Todo notes are inserted whereever more work is
required.

1. The definition of a struct that contains all parameters and the return value
of a given function.
Required in: ./kernel/ibv.c

  Example:
  typedef struct {
      // Parameters:
      struct ibv_mr * mr;
      int flags;
      struct ibv_pd * pd;
      // Return value:
      int ret;
  } __attribute__((packed)) uhyve_ibv_rereg_mr_t;

2. The definition of the kernel space function that sends a KVM exit IO to
uhyve.
Required in: ./kernel/ibv.c

  Example:
  int ibv_rereg_mr(struct ibv_mr * mr, int flags, struct ibv_pd * pd) {
      uhyve_ibv_rereg_mr_t uhyve_args;
      uhyve_args->mr = (struct ibv_mr *) virt_to_phys((size_t) mr);
      uhyve_args->flags = flags;
      uhyve_args->pd = (struct ibv_pd *) virt_to_phys((size_t) pd);

      uhyve_send(UHYVE_PORT_IBV_REREG_MR, (unsigned) virt_to_phys((size_t) &uhyve_args));

      return uhyve_args.ret;
  }

3. TODO The switch-case that catches the KVM exit IO sent to uhyve by the kernel.
Required in: ./tool/uhyve.c

  Example:
  case UHYVE_PORT_IBV_REREG_MR: {
    unsigned data = *((unsigned*)((size_t)run+run->io.data_offset));
    uhyve_ibv_rereg_mr_t * args = (uhyve_ibv_rereg_mr_t *) (guest_mem + data);

    int host_ret = ibv_rereg_mr(guest_mem+(size_t)args->mr, flags, guest_mem+(size_t)args->pd);
    args->ret = host_ret;
    break;
  }

The script also generates an enum mapping all functions to KVM exit IO port
names and numbers.
Required in: ./tool/uhyve-ibv.h

  Example:
  typedef enum {
    UHYVE_PORT_IBV_WC_STATUS_STR = 0x510,
    UHYVE_PORT_IBV_RATE_TO_MULT = 0x511,
    UHYVE_PORT_MULT_TO_IBV_RATE = 0x512,
    // ...
  } uhyve_ibv_t;
"""

from __future__ import print_function
from parser import generate_struct_conversions


# Path of the input file containing function prototypes.
SRC_PATH = "function-prototypes.txt"

# Paths of the files that are generated by the script.
KERNEL_GEN_PATH = "GEN-kernel.c"
KERNEL_HEADER_GEN_PATH = "GEN-kernel-header.h"
UHYVE_CASES_GEN_PATH = "GEN-tools-uhyve.c"
UHYVE_IBV_HEADER_GEN_PATH = "GEN-tools-uhyve-ibv-ports.h"
INCLUDE_STDDEF_GEN_PATH = "GEN-include-hermit-stddef.h"
#  UHYVE_IBV_HEADER_STRUCTS_GEN_PATH = "GEN-tools-uhyve-ibv-structs.h"
UHYVE_HOST_FCNS_GEN_PATH = "GEN-tools-uhyve-ibv.c"
#  VERBS_HEADER_PATH = "verbs-0.h"

# Starting number of the sequence used for IBV ports.
PORT_NUMBER_START = 0x610

TABS = ["", "\t", "\t\t", "\t\t\t", "\t\t\t\t"]
NEWLINES = ["", "\n", "\n\n"]

class Type:
  def __init__(self, string):
    ts = string

    #  if len(string) > 2 and string[-1] is "*":
      #  if string[-2] is "*" and string[-3] is not " ":
        #  ts = string[:-2] + " **"
      #  elif string[-2] is not " ":
        #  ts = string[:-1] + " *"

    self.type_string     = ts
    self.type_components = ts.split(" ")

  def get_struct_name(self):
    name = ""
    if is_struct():
      name = self.type_components[1]
    return name

  def is_struct(self):
    return self.type_components[0] == "struct"

  def is_char_arr(self):
    return self.is_pointer() and "char" in self.type_components

  def is_pointer(self):
    return self.type_components[-1] == "*"

  def is_pointer_pointer(self):
    return self.type_components[-1] == "**"

  def is_void(self):
    return self.type_string == "void"


class FunctionParameter:
  def __init__(self, string):
    components = string.split(" ")
    type_string = " ".join(components[:-1])

    #  print("string in FunctionParameter: ", string)

    self.type = Type(type_string)
    self.name = components[-1]

  def get_full_expression(self):
    return self.type.type_string + " " + self.name

  def get_struct_name(self):
    return self.type.get_struct_name()

  def is_struct(self):
    return self.type.is_struct()

  def is_pointer(self):
    return self.type.is_pointer()

  def is_pointer_pointer(self):
    return self.type.is_pointer_pointer()


class FunctionPrototype:
  def __init__(self, string):
    parens_split = string.split("(")
    ret_and_name = parens_split[0].split(" ")
    all_params = parens_split[-1].split(")")[0]
    param_strings = all_params.split(",")

    self.parameters    = [FunctionParameter(p) for p in param_strings]
    self.ret           = Type(" ".join(ret_and_name[:-1]))
    self.function_name = ret_and_name[-1]

  def generate_args_struct(self):
    """Generates the struct to hold a function's parameters and return value.

    Returns:
    Generated struct as string.
    """
    code = "typedef struct {\n"

    code += "\t// Parameters:\n"
    for param in self.parameters or []:
      code += "\t{0};\n".format(param.get_full_expression())

    if not self.ret.is_void():
      code += "\t// Return value:\n"
      code += "\t{0} ret;\n".format(self.ret.type_string)

    code += "}} __attribute__((packed)) {0};\n\n".format(self.get_args_struct_name())

    return code

  def generate_function_declaration(self):
    return "{} {}({});\n".format(self.ret.type_string, self.function_name, 
                                 self.get_string_of_parameters())

  def get_string_of_parameters(self):
    return ", ".join([param.get_full_expression() for param in self.parameters])

  def generate_uhyve_function_declaration(self):
    name = self.get_uhyve_call_function_name()
    return "void {0}(struct kvm_run * run, uint8_t * guest_mem);\n".format(name)

  def get_uhyve_call_function_name(self):
    return "call_{0}".format(self.function_name)

  def get_num_parameters(self):
    return len(self.parameters)

  def get_parameter_types(self):
    return [param.type.type_string for param in self.parameters]

  def get_port_name(self):
    return "UHYVE_PORT_" + self.function_name.upper()

  def get_args_struct_name(self):
    return "uhyve_{0}_t".format(self.function_name)



# -----------------------------------------------------------------------------


def generate_pretty_comment(string):
  return "/*\n * {0}\n */\n\n".format(string)


def generate_kernel_header_declarations(function_prototypes):
  code = ""
  for pt in function_prototypes:
    code += pt.generate_function_declaration()
  return code


def generate_kernel_function(function_prototype):
  """Generates the kernel function that sends the KVM exit IO to uhyve.

  Returns:
    Generated function as string.
  """
  fnc_name  = function_prototype.function_name
  ret_type  = function_prototype.ret
  params    = function_prototype.parameters
  port_name = function_prototype.get_port_name()

  comma_separated_params = function_prototype.get_string_of_parameters()
  code = "{0} {1}({2}) {{\n".format(ret_type.type_string, fnc_name, comma_separated_params)
  code += "\t{0} uhyve_args;\n".format(function_prototype.get_args_struct_name())

  for p in params or []:
    if p.is_pointer_pointer():
      code += "\t// TODO: Take care of ** parameter.\n"
    else:
      code += "\tuhyve_args.{0} = {0};\n".format(p.name)
  code += "\n"

  code += "\tuhyve_send({0}, (unsigned) virt_to_phys((size_t) &uhyve_args));\n".format(port_name)
  if not ret_type.is_void():
    code += "\n\treturn uhyve_args.ret;\n"
  code += "}\n\n"

  return code

			#  case UHYVE_PORT_SET_IB_POOL_ADDR:
				#  printf("LOG: UHYVE CASE\n");
				#  unsigned data = *((unsigned*)((size_t)run+run->io.data_offset));
				#  uint64_t * temp = (uint64_t*)(guest_mem + data);
				#  /* printf("LOG: Value of uint64 pool start: %" PRIu64 "\n", *temp); */
				#  printf("LOG: Value of uint64 pool start: %p\n", *temp);
				#  ib_pool_addr = (uint8_t*) *temp;
				#  /* printf("LOG: Value of uint8  pool start: %" PRIu8 "\n", ib_pool_addr); */
				#  printf("LOG: Value of uint8  pool start: %p\n", ib_pool_addr);
				#  ib_pool_top = ib_pool_addr;
				#  break;

def generate_uhyve_cases(function_prototypes):
  """ Generates all switch-cases for uhyve's KVM exit IO.

  Returns:
    Generated switch-cases [string]
  """
  code = "\t\t\tcase UHYVE_PORT_SET_IB_POOL_ADDR: {\n"
  code += "\t\t\t\t\tunsigned data = *((unsigned*)((size_t)run+run->io.data_offset));\n"
  code += "\t\t\t\t\tuint64_t * temp = (uint64_t*)(guest_mem + data);\n"
  code += "\t\t\t\t\tib_pool_addr = (uint8_t*) *temp;\n"
  code += "\t\t\t\t\tib_pool_top = ib_pool_addr;\n"
  code += "\t\t\t\t\tbreak;\n"
  code += "\t\t\t}\n\n"

  for pt in function_prototypes:
    call_fnc_name = pt.get_uhyve_call_function_name()
    port_name = pt.get_port_name()

    code += "\t\t\tcase {0}:\n".format(port_name)
    code += "\t\t\t\t{0}(run, guest_mem);\n".format(call_fnc_name)
    code += "\t\t\t\tbreak;\n"

  return code

def generate_uhyve_function(prototype):
  args_struct_name = prototype.get_args_struct_name()
  fnc_name = prototype.function_name
  ret_type = prototype.ret

  code = generate_pretty_comment(fnc_name)
  code += "void call_{0}(struct kvm_run * run, uint8_t * guest_mem) {{\n".format(fnc_name)
  code += "\tprintf(\"LOG: UHYVE - call_{0}\\n\");\n".format(fnc_name)
  code += "\tunsigned data = *((unsigned*) ((size_t) run + run->io.data_offset));\n"
  code += "\t{0} * args = ({0} *) (guest_mem + data);\n\n".format(args_struct_name)

  code += "\tuse_ib_mem_pool = true;\n"
  code += ("\t" + ("args->ret = " if not ret_type.is_void() else "")
                + "{0}(".format(fnc_name))

  if prototype.get_num_parameters() > 0:
    for param in prototype.parameters[:-1] or []:
      code += "args->{}, ".format(param.name)
    code += "args->{});\n".format(prototype.parameters[-1].name)
  code += "\tuse_ib_mem_pool = false;\n}\n\n\n"

  return code


def generate_port_enum(function_prototypes):
  """Generates the enum mapping KVM exit IO port names to port numbers.

  Args:
    function_prototypes: All function names to be mapped to ports as list of strings.

  Returns:
    Generated complete enum.
  """
  code = "typedef enum {\n"
  code += "\tUHYVE_PORT_SET_IB_POOL_ADDR = 0x{0},\n".format(format(PORT_NUMBER_START-1, "X"))
  for num, pt in enumerate(function_prototypes, PORT_NUMBER_START):
    port_name = pt.get_port_name()
    code += "\t{0} = 0x{1},\n".format(port_name, format(num, "X"))
  code += "} uhyve_ibv_t;"

  return code


def generate_port_macros(function_prototypes):
  """Generates the compiler macros mapping KVM exit IO port names to port numbers.

  Args:
    function_names: All function names to be mapped to ports as list of strings.

  Returns:
    Generated list of compiler macros.
  """
  code = "#define UHYVE_PORT_SET_IB_POOL_ADDR 0x{0}\n".format(format(PORT_NUMBER_START-1, "X"))
  for num, pt in enumerate(function_prototypes, PORT_NUMBER_START):
    port_name = pt.get_port_name()
    code += "#define {0} 0x{1}\n".format(port_name, format(num, "X"))
  return code

if __name__ == "__main__":
  prototypes = []

  with open(SRC_PATH, "r") as f:
    for line in f:
      if line:
        prototypes.append(FunctionPrototype(line))

  with open(UHYVE_CASES_GEN_PATH, "w") as f:
    f.write(generate_uhyve_cases(prototypes))

  with open(INCLUDE_STDDEF_GEN_PATH, "w") as f:
    f.write(generate_port_macros(prototypes))

  with open(UHYVE_IBV_HEADER_GEN_PATH, "w") as f:
    f.write(generate_port_enum(prototypes))
    f.write("\n\n")

    for pt in prototypes:
      f.write(pt.generate_args_struct())
    f.write("\n\n")

    for pt in prototypes:
      f.write(pt.generate_uhyve_function_declaration())

  with open(UHYVE_HOST_FCNS_GEN_PATH, "w") as f:
    for pt in prototypes:
      f.write(generate_uhyve_function(pt))

  with open(KERNEL_HEADER_GEN_PATH, "w") as f:
    f.write(generate_kernel_header_declarations(prototypes))

  with open(KERNEL_GEN_PATH, "w") as f:
    for pt in prototypes:
      f.write(generate_pretty_comment(pt.function_name))
      f.write(pt.generate_args_struct())
      f.write(generate_kernel_function(pt))
      f.write("\n")
