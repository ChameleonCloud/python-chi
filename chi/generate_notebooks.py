import chi
import json
import os
import inspect
import re

from chi.util import get_public_network

from chi.server_api_examples import *
from chi.reservation_api_examples import *
from chi.networking_api_examples import *

from chi.reservation_api_examples_generate_notebook import *

import nbformat as nbf

CWD='/home/pruth/work/working'

notebook_list = [ { 'title':          'Python Module: Reserve Node',
                    'function':       'reserve_node',
                    'related_modules':[ 'reserve_floating_ip', 'reserve_network', 'delete_lease' ],
                    'include_code':   [ 'add_node_reservation'],
                    'examples':       [ 'reserve_node_notebook'],
                    'notebook_file':  'reserve_node_notebook.ipynb'},
                 
                 { 'title':          'Python Module: Reserve Floating IP',
                    'function':       'reserve_floating_ip',
                    'related_modules':[ 'reserve_node', 'reserve_network', 'delete_lease' ],
                    'include_code':   [ 'add_fip_reservation'],
                    'examples':       [ 'reserve_floating_ip_notebook'],
                    'notebook_file':  'reserve_floating_ip.ipynb'},
                 
                 { 'title':          'Python Module: Reserve Network',
                    'function':       'reserve_network',
                    'related_modules':[ 'reserve_floating_ip', 'reserve_node', 'delete_lease' ],
                    'include_code':   [ 'add_network_reservation'],
                    'examples':       [ 'reserve_network_notebook'],
                    'notebook_file':  'reserve_network.ipynb'},
                 
                 { 'title':          'Python Module: Delete Lease',
                    'function':       'delete_lease_by_name',
                    'related_modules':[ 'reserve_node' ],
                    'include_code':   [ 'delete_lease_by_id' ],
                    'examples':       [ 'delete_lease_notebook'],
                    'notebook_file':  'delete_lease.ipynb'},
                ]

def run_generate_all_notebooks():
    for n in notebook_list:
        function = n['function']
        print('processing ' + function)
    
        sections={}
        #Build sections structure for current notebook
        sections['title']=get_title(n)
        sections['description']=get_description(n)
        sections['related_modules']=get_related_modules(n)
        #sections['arguments']=get_arguments(n)
        sections['code']=get_code(n)
        sections['examples']=get_examples(n)
    
        #Generate notebook
        nb = generate_notebook(sections)
        
        #Write notebook file
        write_notebook(nb, CWD+'/'+n['notebook_file'])

def generate_notebook(sections):
    nb = nbf.v4.new_notebook()

    nb['metadata']['kernelspec'] ={
                                    "argv": ["python3", "-m", "IPython.kernel",
                                    "-f", "{connection_file}"],
                                    "display_name": "Python 3",
                                    "language": "python"
                                    }
    
    nb['cells'] = [nbf.v4.new_markdown_cell(sections['title']),
                   nbf.v4.new_markdown_cell(sections['description']),
                   nbf.v4.new_markdown_cell(sections['related_modules']),
                   #nbf.v4.new_markdown_cell(sections['arguments']),
                   nbf.v4.new_markdown_cell('### Code'),
                   nbf.v4.new_code_cell(sections['code']),
                   nbf.v4.new_markdown_cell('### Example(s)'),
                   nbf.v4.new_code_cell(sections['examples']),
                   ]



    #print(json.dumps(nb, indent=2))
    return nb

def remove_comments(s):
    r = re.compile(r"(['\"])\1\1(.*?)\1{3}",re.DOTALL)
    return re.sub(r,'',s)


def get_title(notebook):
    return '# ' + notebook['title']

def get_examples(notebook):
    examples = notebook['examples']
    output=''
    
    for example in examples:
        lines = inspect.getsourcelines(globals()[example])
        ##lines = inspect.getsource(create_network)
        signature = lines[0].pop(0)
    
        #white_space = len(lines[0][0]) - len(lines[0][0].lstrip(' '))
        #print('white_space: ' + str(white_space))
        #for l in lines[0]:
        #    output+=l[white_space:]
        #    

        code = inspect.getsource(globals()[example])
        code = code.replace(signature,'')

        code = remove_comments(code)

        #r = re.compile(r"(['\"])\1\1(.*?)\1{3}",re.DOTALL)
        #code = re.sub(r,'',code)

        output += code
    
    return output


def get_arguments(notebook):

    output = '### Arguments\n'
        
    return output


def get_related_modules(notebook):

    output = '### Related Modules\n'
    
    modules = notebook['related_modules']
    for module in modules:
        for notebook in notebook_list:
            if notebook['function'] == module:
                output += '- [Module on '+notebook['function']+'](./'+notebook['notebook_file']+')\n'
        
    return output


def get_description(notebook):
    function_name = notebook['function']
    
    output = '### Description\n'
    
    if globals()[function_name].__doc__:
        output += globals()[function_name].__doc__
    
    #print('docString: '+ docString)
    
    return output


def get_code(notebook):
    function_name = notebook['function']
    include_code = notebook['include_code']
    
    output = ''
    for function in include_code:
        output+= inspect.getsource(globals()[function])
    
    
    output+= inspect.getsource(globals()[function_name])
        
    return output

def write_notebook(nb, file_name):
    print('write notebook: ' + file_name)
    f = open(file_name, "w")
    f.write(json.dumps(nb, indent=2))
    f.close()