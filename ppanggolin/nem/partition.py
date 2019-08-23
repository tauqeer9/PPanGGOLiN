#!/usr/bin/env python3
#coding:utf-8

#default libraries
import logging
import random
import tempfile
import time
from multiprocessing import Pool
import os
import argparse
from collections import defaultdict, Counter
import math
#installed libraries
from tqdm import tqdm
import plotly.offline as out_plotly
import plotly.graph_objs as go
#local libraries
from ppanggolin.pangenome import Pangenome
from ppanggolin.utils import mkOutdir
from ppanggolin.formats import checkPangenomeInfo, writePangenome

#cython library (local)
import nem_stats

pan = None
samples = []

def run_partitioning(nem_dir_path, nb_org, beta, free_dispersion, Q = 3, seed = 42, init="param_file", keep_files = False, itermax=100, just_log_likelihood=False):
    logging.getLogger().debug("run_partitioning...")

    if init=="param_file":
        with open(nem_dir_path+"/nem_file_init_"+str(Q)+".m", "w") as m_file:
            m_file.write("1 ")# 1 to initialize parameter,
            m_file.write(" ".join([str(round(1/float(Q),2)) for q in range(Q-1)])+" ")# 1/Q give the initial proportition to each class (the last proportion is automaticaly determined by substraction in nem)
            mu=[]
            epsilon=[]
            step = 0.5/(math.ceil(Q/2))
            for q in range(1,Q+1):
                if q <= Q/2:
                    mu += ["1"]*nb_org
                    epsilon += [str(step*q)]*nb_org
                else:
                    mu += ["0"]*nb_org
                    epsilon += [str(step*(Q-q+1))]*nb_org

            m_file.write(" ".join(mu)+" "+" ".join(epsilon))

    ALGO           = b"nem" #fuzzy classification by mean field approximation
    MODEL          = b"bern" # multivariate Bernoulli mixture model
    PROPORTION     = b"pk" #equal proportion :  "p_"     varying proportion : "pk"
    VARIANCE_MODEL = b"skd" if free_dispersion else b"sk_"#one variance per partition and organism : "sdk"      one variance per partition, same in all organisms : "sd_"   one variance per organism, same in all partion : "s_d"    same variance in organisms and partitions : "s__"
    CONVERGENCE    = b"clas"
    CONVERGENCE_TH = 0.01
    # (INIT_SORT, INIT_RANDOM, INIT_PARAM_FILE, INIT_FILE, INIT_LABEL, INIT_NB) = range(0,6)
    INIT_RANDOM, INIT_PARAM_FILE = range(1,3)
    logging.getLogger().debug("Running NEM...")
    logging.getLogger().debug([nem_dir_path.encode('ascii')+b"/nem_file",
        Q,
        ALGO,
        beta,
        CONVERGENCE,
        CONVERGENCE_TH,
        b"fuzzy",
        itermax,
        True,
        MODEL,
        PROPORTION,
        VARIANCE_MODEL,
        INIT_PARAM_FILE if init in ["param_file","init_from_old"] else INIT_RANDOM,
        nem_dir_path.encode('ascii')+b"/nem_file_init_"+str(Q).encode('ascii')+b".m",
        nem_dir_path.encode('ascii')+b"/nem_file_"+str(Q).encode('ascii'),
        seed])
    nem_stats.nem(Fname         = nem_dir_path.encode('ascii')+b"/nem_file",
                nk              = Q,
                algo            = ALGO,
                beta            = beta,
                convergence     = CONVERGENCE,
                convergence_th  = CONVERGENCE_TH,
                format          = b"fuzzy",
                it_max          = itermax,
                dolog           = True,
                model_family    = MODEL,
                proportion      = PROPORTION,
                dispersion      = VARIANCE_MODEL,
                init_mode       = INIT_PARAM_FILE if init in ["param_file","init_from_old"] else INIT_RANDOM,
                init_file       = nem_dir_path.encode('ascii')+b"/nem_file_init_"+str(Q).encode('ascii')+b".m",
                out_file_prefix = nem_dir_path.encode('ascii')+b"/nem_file_"+str(Q).encode('ascii'),
                seed            = seed)

    logging.getLogger().debug("After running NEM...")

    no_nem = False
    if os.path.isfile(nem_dir_path+"/nem_file_"+str(Q)+".uf"):
        logging.getLogger().debug("Reading NEM results...")
    elif not just_log_likelihood:
        # logging.getLogger().warning("No NEM output file found: "+ nem_dir_path+"/nem_file_"+str(Q)+".uf")
        no_nem = True
    else:
        logging.getLogger().debug("No NEM output file found: "+ nem_dir_path+"/nem_file_"+str(Q)+".uf")
        no_nem = True
    index_fam = []
    all_parameters = {}

    with open(nem_dir_path+"/nem_file.index","r") as index_nem_file:
        for line in index_nem_file:
            index_fam.append(line.split("\t")[1].strip())

    partitions_list = ["U"] * len(index_fam)
    all_parameters  = {}
    U,D,log_likelihood = [None]*3#L,Z, error
    entropy         = None
    try:
        with open(nem_dir_path+"/nem_file_"+str(Q)+".uf","r") as partitions_nem_file, open(nem_dir_path+"/nem_file_"+str(Q)+".mf","r") as parameters_nem_file:
            parameters      = parameters_nem_file.readlines()
            U,D,_,log_likelihood,_,_ = [float(p) for p in parameters[2].split()]#L,Z, error
            logging.getLogger().debug("U="+str(U))
            logging.getLogger().debug("D="+str(D))
            logging.getLogger().debug("log_likelihood="+str(log_likelihood))
            sum_mu_k       = []
            sum_epsilon_k  = []

            for k, line in enumerate(parameters[-Q:]):
                logging.getLogger().debug(line)
                vector = line.split()
                mu_k = [bool(float(mu_kj)) for mu_kj in vector[0:nb_org]]
                logging.getLogger().debug(mu_k)
                logging.getLogger().debug(len(mu_k))
                epsilon_k = [float(epsilon_kj) for epsilon_kj in vector[nb_org+1:]]
                logging.getLogger().debug(epsilon_k)
                logging.getLogger().debug(len(epsilon_k))
                proportion = float(vector[nb_org])
                logging.getLogger().debug(proportion)
                sum_mu_k.append(sum(mu_k))
                logging.getLogger().debug(sum(mu_k))
                sum_epsilon_k.append(sum(epsilon_k))
                logging.getLogger().debug(sum(epsilon_k))
                if k == 0:
                    all_parameters["persistent"]=(mu_k,epsilon_k,proportion)
                elif k == Q-1:
                    all_parameters["cloud"]=(mu_k,epsilon_k,proportion)
                else:
                    all_parameters["shell_"+str(k)]=(mu_k,epsilon_k,proportion)

            partition               = {}
            partition[0]   = "P"#PERSISTENT
            partition[Q-1] = "C"#CLOUD
            for i in range(1,Q-1):
                partition[i]="S"+str(i)
            entropy = 0

            for i, line in enumerate(partitions_nem_file):
                elements = [float(el) for el in line.split()]
                if just_log_likelihood:
                    entropy +=sum([math.log(float(el))*float(el) if float(el)>0 else 0 for el in elements])
                else:
                    max_prob = max([float(el) for el in elements])
                    positions_max_prob = [pos for pos, prob in enumerate(elements) if prob == max_prob]
                    # logging.getLogger().debug(positions_max_prob)
                    # logging.getLogger().debug(i)
                    if (len(positions_max_prob)>1 or max_prob<0.5):
                        partitions_list[i]="S_"#SHELL in case of doubt gene families is attributed to shell
                    else:
                        partitions_list[i]=partition[positions_max_prob.pop()]
            #logging.getLogger().debug(index.keys())
    except IOError:
        logging.getLogger().debug("partitioning did not work (the number of organisms used is probably too low), see logs here to obtain more details "+nem_dir_path+"/nem_file_"+str(Q)+".log")
        return  [{},None,None]#return empty objects.
    except ValueError:
        ## return the default partitions_list which correspond to undefined
        pass

    if not keep_files and no_nem is False:
        os.remove(nem_dir_path+"/nem_file_"+str(Q)+".uf")
        os.remove(nem_dir_path+"/nem_file_"+str(Q)+".mf")
        os.remove(nem_dir_path+"/nem_file_"+str(Q)+".log")
        os.remove(nem_dir_path+"/nem_file_"+str(Q)+".stderr")
        os.remove(nem_dir_path+"/nem_file_init_"+str(Q)+".m")
        os.remove(nem_dir_path+"/nem_file.index")
        os.remove(nem_dir_path+"/nem_file.dat")
        os.remove(nem_dir_path+"/nem_file.nei")
        os.remove(nem_dir_path+"/nem_file.str")

    if just_log_likelihood:
        return (tuple([Q,log_likelihood,entropy]))
    else:
        return((dict(zip(index_fam, partitions_list)),all_parameters,log_likelihood))

def nemSingle(args):
    return run_partitioning(*args)

def partition_nem(index, tmpdir, beta, sm_degree, free_dispersion, Q, seed, init, keep_tmp_files):
    currtmpdir = tmpdir + "/" +str(index)#unique directory name
    samp = samples[index]#org_samples accessible because it is a global variable.
    edges_weight, nb_fam = write_nem_input_files(tmpdir=currtmpdir,organisms= set(samp), sm_degree = sm_degree)
    return run_partitioning( currtmpdir, len(samp), beta * (nb_fam/edges_weight), free_dispersion, Q = Q, seed = seed, init = init, keep_files = keep_tmp_files)

def nemSamples(pack):
    #run partitionning
    return partition_nem(*pack)

def write_nem_input_files( tmpdir, organisms, sm_degree):

    mkOutdir(tmpdir, force = False)
    total_edges_weight = 0

    with open(tmpdir+"/column_org_file", "w") as org_file:
        org_file.write(" ".join([ f'"{org.name}"' for org in organisms]) + "\n")


    logging.getLogger().debug("Writing nem_file.str nem_file.index nem_file.nei and nem_file.dat files")
    with open(tmpdir+"/nem_file.str", "w") as str_file,\
        open(tmpdir+"/nem_file.index", "w") as index_file,\
        open(tmpdir+"/nem_file.nei", "w") as nei_file,\
        open(tmpdir+"/nem_file.dat", "w") as dat_file:

        nei_file.write("1\n")
        index_fam = {}

        index_org = {}
        default_dat = []
        for index, org in enumerate(organisms):
            default_dat.append('0')
            index_org[org] = index

        for fam in pan.geneFamilies:
            #could use bitarrays if this part is limiting?
            if not organisms.isdisjoint(fam.organisms):
                currDat = list(default_dat)
                curr_orgs = fam.organisms & organisms
                for org in curr_orgs:
                    currDat[index_org[org]] = "1"
                dat_file.write("\t".join(currDat) + "\n")
                index_fam[fam] = len(index_fam) +1
                index_file.write(f"{len(index_fam)}\t{fam.name}\n")
        # logging.getLogger().info("write graph : "+getCurrentRAM())

        for fam in index_fam.keys():
            row_fam = []
            row_dist_score = []
            neighbor_number = 0
            for edge in fam.edges:#iter on the family's edges.
                coverage = sum([ len(gene_list) for org, gene_list in edge.organisms.items() if org in organisms ])
                if coverage == 0:
                    continue#nothing interesting to write, this edge does not exist with this subset of organisms.
                distance_score = coverage / len(organisms)
                total_edges_weight +=distance_score
                row_fam.append(str(index_fam[ edge.target if fam == edge.source else edge.source]))
                row_dist_score.append(str(round(distance_score, 4)))
                neighbor_number+=1
            if neighbor_number > 0 and float(neighbor_number) < sm_degree:
                nei_file.write('\t'.join([str(item) for sublist in [[index_fam[fam]],[neighbor_number],row_fam,row_dist_score] for item in sublist])+"\n")
            else:
                nei_file.write(str(index_fam[fam]) + "\t0\n")

        str_file.write("S\t"+str(len(index_fam))+"\t"+str(len(organisms))+"\n")
    return total_edges_weight/2, len(index_fam)

def evaluate_nb_partitions(organisms, sm_degree, free_dispersion, chunk_size, Qrange, ICL_margin, draw_ICL, cpu, tmpdir, seed, outputdir):
    Newtmpdir = tmpdir + "/eval_partitions"
    ChosenQ = 3
    if len(organisms) > chunk_size:
        select_organisms = set(random.sample(set(organisms), chunk_size))
    else:
        select_organisms = set(organisms)

    _, nb_fam = write_nem_input_files( Newtmpdir, select_organisms, sm_degree)
    max_icl_Q      = 0
    argsPartitionning = []
    for q in range(Qrange[0]-1, Qrange[1]):
        argsPartitionning.append((Newtmpdir, len(select_organisms), 0, free_dispersion, q, seed, "param_file", True, 10, True))#those arguments follow the order of the arguments of run_partitionning
    allLogLikelihood = []

    if cpu > 1:
        bar = tqdm(range(len(argsPartitionning)), unit = "Number of number of partitions")
        with Pool(processes = cpu) as p:
            for result in p.imap_unordered(nemSingle, argsPartitionning):
                allLogLikelihood.append(result)
                bar.update()
            p.close()
            p.join()
        bar.close()
    else:#for the case where it is called in a daemonic subprocess with a single cpu
        for arguments in argsPartitionning:
            allLogLikelihood.append(nemSingle(arguments))

    def calculate_BIC(log_likelihood,nb_params,nb_points):
        return( log_likelihood - 0.5 *(math.log(nb_points) * nb_params))

    all_BICs = defaultdict(float)
    all_ICLs = defaultdict(float)
    all_LLs  = defaultdict(float)
    for Q_candidate, log_likelihood, entropy in allLogLikelihood:
        if log_likelihood is not None:
            all_BICs[Q_candidate] = calculate_BIC(log_likelihood,Q_candidate * (len(select_organisms) + 1 + (len(select_organisms) if free_dispersion else 1)),nb_fam)
            all_ICLs[Q_candidate] = all_BICs[Q_candidate] - entropy
            all_LLs[Q_candidate]  = log_likelihood

    ChosenQ = 3
    if len(all_BICs)>3:
        max_icl_Q  = max(all_ICLs, key=all_ICLs.get)
        delta_ICL  = (all_ICLs[max_icl_Q]-min(all_ICLs.values()))*ICL_margin
        best_Q = min({q for q, icl in all_ICLs.items() if icl>=all_ICLs[max_icl_Q]-delta_ICL and q <= max_icl_Q})
        ChosenQ = best_Q if best_Q >=3 else ChosenQ
    if len(all_BICs)>0 and draw_ICL:
        traces = []
        traces.append(go.Scatter(x=[ key for key in sorted(all_BICs.keys()) ],
                                    y=[ all_BICs[key] for key in sorted(all_BICs.keys()) ],
                                    name = "BIC",
                                    mode = "lines+markers"))
        traces.append(go.Scatter(x=[ key for key in sorted(all_ICLs.keys()) ],
                                    y=[ all_ICLs[key] for key in sorted(all_ICLs.keys()) ],
                                    name = "ICL",
                                    mode = "lines+markers"))
        traces.append(go.Scatter(x=[ key for key in sorted(all_LLs.keys()) ],
                                    y=[ all_LLs[key] for key in sorted(all_LLs.keys()) ],
                                    name = "log likelihood",
                                    mode = "lines+markers"))
        layout = go.Layout(title = 'ICL curve (best Q is '+str(best_Q)+', ICL_th= is '+str(ICL_margin)+")",
                            titlefont = dict(size = 20),
                            xaxis = dict(title='number of partitions'),
                            yaxis = dict(title='ICL, BIC, log likelihood'),
                            shapes=[dict(type='line', x0=best_Q, x1=best_Q, y0=0, y1=all_ICLs[best_Q], line = dict(dict(width=1, dash='dashdot', color="black"))),
                                    dict(type='line', x0=max_icl_Q, x1=max_icl_Q, y0=0, y1=all_ICLs[max_icl_Q], line = dict(dict(width=1, dash='dashdot', color="black"))),
                                    dict(type='line', x0=best_Q, x1=max_icl_Q, y0=all_ICLs[max_icl_Q], y1=all_ICLs[max_icl_Q], line = dict(dict(width=1, dash='dashdot', color="black"))),
                                    dict(type='line', x0=2, x1=Qrange[1], y0=all_ICLs[best_Q], y1=all_ICLs[best_Q], line = dict(dict(width=1, dash='dashdot', color="black")))])
        fig = go.Figure(data=traces, layout=layout)
        out_plotly.plot(fig, filename=outputdir+"/ICL_curve_Q"+str(best_Q)+".html", auto_open=False)
    return ChosenQ

def partition(pangenome, outputdir = None, beta = 2.5, sm_degree = float("inf"), free_dispersion=False, chunk_size=500, Q=-1, Qrange=None, ICL_margin=0.05, draw_ICL = False, cpu = 1, tmpdir="/dev/shm", seed = 42, keep_tmp_files = False):

    Qrange = Qrange or [3,21]
    global pan
    global samples
    pan = pangenome

    if draw_ICL and outputdir is None:
        raise Exception("Combination of option impossible: You asked to draw the ICL curves but did not provide an output directory!")

    checkPangenomeInfo(pangenome, needAnnotations=True, needFamilies=True, needGraph=True)
    organisms = set(pangenome.organisms)
    if keep_tmp_files:
        tmpdir = tmpdir + "ppanggolin_output"+time.strftime("_DATE%Y-%m-%d_HOUR%H.%M.%S", time.localtime())+"_PID"
        os.makedirs(tmpdir)
    else:
        tmpdirObj = tempfile.TemporaryDirectory(dir=tmpdir)
        tmpdir = tmpdirObj.name

    if len(organisms) <= 10:
        logging.getLogger().warning(f"The number of selected organisms is too low ({len(organisms)} organisms used) to robustly partition the graph")

    if Q < 3:
        logging.getLogger().info("Estimating the optimal number of partitions...")
        Q = evaluate_nb_partitions( organisms, sm_degree, free_dispersion, chunk_size, Qrange, ICL_margin, draw_ICL, cpu, tmpdir, seed, outputdir)
        logging.getLogger().info(f"The number of partitions has been evaluated at {Q}")

    init = "param_file"

    partitionning_results = {}

    families = set()
    cpt = 0
    cpt_partition = {}
    random.seed(seed)

    for fam in pangenome.geneFamilies:
        families.add(fam)
        if chunk_size < len(organisms):
            cpt_partition[fam.name] = {"P":0,"S":0,"C":0,"U":0}

    start_partitionning = time.time()
    logging.getLogger().info("Partitioning...")
    pansize = len(families)
    if chunk_size < len(organisms):
        validated = set()

        def validate_family(result):
            for node, nem_class in result[0].items():
                cpt_partition[node][nem_class[0]]+=1
                sum_partionning = sum(cpt_partition[node].values())
                if (sum_partionning > len(organisms)/chunk_size and max(cpt_partition[node].values()) >= sum_partionning*0.5) or (sum_partionning > len(organisms)):
                    if node not in validated:
                        if max(cpt_partition[node].values()) < sum_partionning*0.5:
                            cpt_partition[node]["U"] = len(organisms) #if despite len(select_organisms) partionning, an abosolute majority is not found then the families is set to undefined
                        validated.add(node)

        org_nb_sample = Counter()
        for org in organisms:
            org_nb_sample[org] = 0
        condition = len(organisms)/chunk_size
        while len(validated) < pansize:
            prev = len(samples)#if we've been sampling already, samples is not empty.
            while not all(val >= condition for val in org_nb_sample.values()):#each family must be tested at least len(select_organisms)/chunk_size times.
                shuffled_orgs = list(organisms)#copy select_organisms
                random.shuffle(shuffled_orgs)#shuffle the copied list
                while len(shuffled_orgs) > chunk_size:
                    samples.append(set(shuffled_orgs[:chunk_size]))
                    for org in samples[-1]:
                        org_nb_sample[org] +=1
                    shuffled_orgs = shuffled_orgs[chunk_size:]
            args = []
            # tmpdir, beta, sm_degree, free_dispersion, Q, seed
            for i, _ in enumerate(samples[prev:], start=prev):
                args.append((i, tmpdir, beta,sm_degree, free_dispersion, Q, seed, init, keep_tmp_files))

            logging.getLogger().info("Launching NEM")

            with Pool(processes = cpu) as p:
                #launch partitionnings
                bar = tqdm(range(len(args)), unit = " samples partitionned")
                for result in p.imap_unordered(nemSamples, args):
                    validate_family(result)
                    bar.update()

                bar.close()
                condition +=1#if len(validated) < pan_size, we will want to resample more.
                p.close()
                p.join()

        for fam, data in cpt_partition.items():
            partitionning_results[fam]=max(data, key=data.get)

        ## need to compute the median vectors of each partition ???
        partitionning_results = [partitionning_results,[]]##introduces a 'non feature'.

        logging.getLogger().info(f"Did {len(args)} partitionning with chunks of size {chunk_size} among {len(organisms)} genomes in {round(time.time() - start_partitionning,2)} seconds.")
    else:
        edges_weight, nb_fam = write_nem_input_files( tmpdir+"/"+str(cpt)+"/", organisms, sm_degree = sm_degree)
        partitionning_results = run_partitioning( tmpdir+"/"+str(cpt)+"/", len(organisms), beta * (nb_fam/edges_weight), free_dispersion, Q = Q, seed = seed, init = init)
        if partitionning_results == [{},None,None]:
            raise Exception("Statistical partitionning does not work on your data. This usually happens because you used very few (<15) genomes.")
        cpt+=1
        logging.getLogger().info(f"Partitionned {len(organisms)} genomes in {round(time.time() - start_partitionning,2)} seconds.")


    pangenome.savePartitionParameters(Q, beta, free_dispersion, sm_degree, partitionning_results[1], chunk_size)

    for famName, partition in partitionning_results[0].items():
        pangenome.getGeneFamily(famName).partition = partition

    pangenome.status["partitionned"] = "Computed"
    if not keep_tmp_files:
        tmpdirObj.cleanup()
    #else write files somewhere ???

def launch(args):
    """
        main code when launch partition from the command line.
    """
    if args.draw_ICL or args.keep_tmp_files:
        mkOutdir(args.output, args.force)
    pangenome = Pangenome()
    pangenome.addFile(args.pangenome)
    partition(pangenome, args.output, args.beta, args.max_degree_smoothing, args.free_dispersion, args.chunk_size, args.nb_of_partitions, args.qrange, args.ICL_margin, args.draw_ICL, args.cpu, args.tmpdir, args.seed, args.keep_tmp_files)
    writePangenome(pangenome,pangenome.file, args.force)

def partitionSubparser(subparser):
    parser = subparser.add_parser("partition",help = "Partition the pangenome graph", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    optional = parser.add_argument_group(title = "Optional arguments")
    optional.add_argument("-b","--beta", required = False, default = 2.5, type = float, help = "beta is the strength of the smoothing using the graph topology during partitionning. 0 will deactivate spatial smoothing.")
    optional.add_argument("-ms","--max_degree_smoothing",required = False, default = float("inf"), help = "max. degree of the nodes to be included in the smoothing process.")
    optional.add_argument('-o','--output', required=False, type=str, default="ppanggolin_output"+time.strftime("_DATE%Y-%m-%d_HOUR%H.%M.%S", time.localtime())+"_PID"+str(os.getpid()), help="Output directory")
    optional.add_argument("-fd","--free_dispersion",required = False, default = False, action = "store_true",help = "use if the dispersion around the centroid vector of each partition during must be free. It will be the same for all organisms by default.")
    optional.add_argument("-ck","--chunk_size",required=False, default = 500, type = int, help = "Size of the chunks when performing partitionning using chunks of organisms. Chunk partitionning will be used automatically if the number of genomes is above this number.")
    optional.add_argument("-Q","--nb_of_partitions",required=False, default=-1, type=int, help = "Number of partitions to use. Must be at least 3. If under 3, it will be detected automatically.")
    optional.add_argument("-Qmm","--qrange",nargs=2,required = False, type=int, default=[3,20], help="Range of Q values to test when detecting Q automatically. Default between 3 and 20.")
    optional.add_argument("-im","--ICL_margin",required = False, type = float, default = 0.05, help = "Q is detected automatically by maximizing ICL. However at some point the ICL reaches a plateau. Therefore we are looking for the minimal value of Q without significative gain from the larger values of Q measured by ICL. For that we take the lowest Q that is found within a given 'margin' of the maximal ICL value. Basically, change this option only if you truly understand it, otherwise just leave it be.")
    optional.add_argument("--draw_ICL", required =False, default = False, action="store_true",help = "Use if you can to draw the ICL curve for all of the tested Q values. Will not be done if Q is given.")
    optional.add_argument("--keep_tmp_files",required = False, default = False, action = "store_true",help = "Use if you want to keep the temporary NEM files")
    #use former partitionning ?????
    #soft core ???
    required = parser.add_argument_group(title = "Required arguments", description = "One of the following arguments is required :")
    required.add_argument('-p','--pangenome',  required=True, type=str, help="The pangenome .h5 file")

    return parser