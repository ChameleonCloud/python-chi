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
from chi.generate_notebooks_config import *

import nbformat as nbf



def get_group_subfolder(group_name):
    for group in notebooks_config['groups']:
        if group['name'] == group_name:
            return group['subfolder']

def get_abs_notebook_path(notebook):
    return notebooks_config['base_folder'] + '/' + get_group_subfolder(notebook['group'])+ '/' + notebook['notebook_file']

def get_rel_notebook_path(notebook):
    return get_group_subfolder(notebook['group'])+ '/' + notebook['notebook_file']


def run_generate_all_notebooks():
    
    for module in notebooks_config['modules']:
        function = module['function']
        print('processing ' + function)
    
        sections={}
        #Build sections structure for current notebook
        sections['title']=get_title(module)
        sections['description']=get_description(module)
        sections['related_modules']=get_related_modules(module)
        #sections['arguments']=get_arguments(module)
        sections['code']=get_code(module)
        sections['examples']=get_examples(module)
    
        #Generate notebook
        nb = generate_notebook(sections)
        
        #Write notebook file
        #write_notebook(nb, CWD + '/' + notebook_group_subfolders[n['group']] + '/' + n['notebook_file'])
        write_notebook(nb,get_rel_notebook_path(module))
        
    #Generate Index Notebook
    index_notebook = generate_index()
    write_notebook(index_notebook,notebooks_config['base_folder']+'/index.ipynb')
    
def generate_index():
    nb = nbf.v4.new_notebook()

    #nb['metadata']['kernelspec'] ={
    #                                "argv": ["python3", "-m", "IPython.kernel",
    #                                "-f", "{connection_file}"],
    #                                "display_name": "Python 3",
    #                                "language": "python"
    #                                }

    nb['cells'] = [nbf.v4.new_markdown_cell('## List of all Chameleon Python Tutorials and Modules\n')]
    
    for group in notebooks_config['groups']:
        cell_str = '#### ' + group['name'] + "\n"
        for notebook in notebooks_config['modules']:
            if group['name'] == notebook['group']:
                cell_str += '- [' + notebook['title'] + '](' + get_rel_notebook_path(notebook) + ')\n'
        nb['cells'].append(nbf.v4.new_markdown_cell(cell_str))

    #print(json.dumps(nb, indent=2))
    return nb

def generate_notebook(sections):
    nb = nbf.v4.new_notebook()

    #nb['metadata']['kernelspec'] ={
    #                                "argv": ["python3", "-m", "IPython.kernel",
    #                                "-f", "{connection_file}"],
    #                                "display_name": "Python 3",
    #                                "language": "python"
    #                                }

    
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
        
    for related_module in notebook['related_modules']:
        for module in notebooks_config['modules']:
            if module['function'] == related_module:
                output += '- ['+module['title']+'](../' + get_rel_notebook_path(module) +')\n'
        
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
    
    if not os.path.exists(os.path.dirname(file_name)):
        try:
            os.makedirs(os.path.dirname(file_name))
        except OSError as exc: 
            if exc.errno != errno.EEXIST:
                raise
    
    f = open(file_name, "w")
    f.write(json.dumps(nb, indent=2))
    f.close()