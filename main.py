import sys
sys.path.append(".")
from query_representation.query import *
from evaluation.eval_fns import *
from cardinality_estimation.featurizer import *
from cardinality_estimation.algs import *
from cardinality_estimation.fcnn import FCNN
from cardinality_estimation.mscn import MSCN

import glob
import argparse
import random
import json

import klepto
from sklearn.model_selection import train_test_split
import pdb
import copy

import wandb
import logging
logger = logging.getLogger("wandb")
logger.setLevel(logging.ERROR)

def eval_alg(alg, eval_funcs, qreps, samples_type, featurizer=None):
    '''
    '''
    np.set_printoptions(formatter={'float': lambda x: "{0:0.3f}".format(x)})

    start = time.time()
    alg_name = alg.__str__()
    exp_name = alg.get_exp_name()
    ests = alg.test(qreps)

    for efunc in eval_funcs:
        rdir = None

        if args.result_dir is not None:
            rdir = os.path.join(args.result_dir, exp_name)
            make_dir(rdir)

        errors = efunc.eval(qreps, ests, args=args, samples_type=samples_type,
                result_dir=rdir, user = args.user, db_name = args.db_name,
                db_host = args.db_host, port = args.port,
                num_processes = args.num_eval_processes,
                alg_name = alg_name,
                save_pdf_plans=args.save_pdf_plans,
                use_wandb=args.use_wandb, featurizer=featurizer,
                alg=alg)

        print("{}, {}, {}, #samples: {}, {}: mean: {}, median: {}, 99p: {}"\
                .format(args.db_name, samples_type, alg, len(errors),
                    efunc.__str__(),
                    np.round(np.mean(errors),3),
                    np.round(np.median(errors),3),
                    np.round(np.percentile(errors,99),3)))

        if args.use_wandb:
            loss_key = "Final-{}-{}-{}".format(str(efunc),
                                                   samples_type,
                                                   "mean")
            wandb.run.summary[loss_key] = np.round(np.mean(errors),3)

            loss_key = "Final-{}-{}-{}".format(str(efunc),
                                                   samples_type,
                                                   "99p")
            wandb.run.summary[loss_key] = np.round(np.percentile(errors,99), 3)

    print("all loss computations took: ", time.time()-start)

def get_alg(alg):
    if alg == "saved":
        assert args.model_dir is not None
        return SavedPreds(model_dir=args.model_dir)
    elif alg == "postgres":
        return Postgres()
    elif alg == "true":
        return TrueCardinalities()
    elif alg == "joinkeys":
        return TrueJoinKeys()
    elif alg == "true_rank":
        return TrueRank()
    elif alg == "true_random":
        return TrueRandom()
    elif alg == "true_rank_tables":
        return TrueRankTables()
    elif alg == "random":
        return Random()
    elif alg == "rf":
        return RandomForest(grid_search = False,
                n_estimators = 100,
                max_depth = 10,
                lr = 0.01)
    elif alg == "xgb":
        return XGBoost(grid_search=False, tree_method="hist",
                       subsample=1.0, n_estimators = 100,
                       max_depth=10, lr = 0.01)
    elif alg == "fcnn":
        return FCNN(max_epochs = args.max_epochs, lr=args.lr,
                training_opt = args.training_opt,
                opt_lr = args.opt_lr,
                swa_start = args.swa_start,
                mask_unseen_subplans = args.mask_unseen_subplans,
                subplan_level_outputs=args.subplan_level_outputs,
                normalize_flow_loss = args.normalize_flow_loss,
                heuristic_unseen_preds = args.heuristic_unseen_preds,
                onehot_dropout=args.onehot_dropout,
                onehot_reg=args.onehot_reg,
                onehot_reg_decay=args.onehot_reg_decay,
                cost_model = args.cost_model,
                eval_fns = args.eval_fns,
                use_wandb = args.use_wandb,
                mb_size = args.mb_size,
                weight_decay = args.weight_decay,
                load_query_together = args.load_query_together,
                result_dir = args.result_dir,
                num_hidden_layers=args.num_hidden_layers,
                eval_epoch = args.eval_epoch,
                optimizer_name=args.optimizer_name,
                clip_gradient=args.clip_gradient,
                loss_func_name = args.loss_func_name,
                hidden_layer_size = args.hidden_layer_size)
    elif alg == "mscn":
        return MSCN(max_epochs = args.max_epochs, lr=args.lr,
                inp_dropout = args.inp_dropout,
                hl_dropout = args.hl_dropout,
                comb_dropout = args.comb_dropout,
                training_opt = args.training_opt,
                opt_lr = args.opt_lr,
                swa_start = args.swa_start,
                mask_unseen_subplans = args.mask_unseen_subplans,
                subplan_level_outputs=args.subplan_level_outputs,
                normalize_flow_loss = args.normalize_flow_loss,
                heuristic_unseen_preds = args.heuristic_unseen_preds,
                cost_model = args.cost_model,
                use_wandb = args.use_wandb,
                eval_fns = args.eval_fns,
                load_padded_mscn_feats = args.load_padded_mscn_feats,
                mb_size = args.mb_size,
                weight_decay = args.weight_decay,
                load_query_together = args.load_query_together,
                result_dir = args.result_dir,
                onehot_dropout=args.onehot_dropout,
                onehot_mask_truep=args.onehot_mask_truep,
                onehot_reg=args.onehot_reg,
                onehot_reg_decay=args.onehot_reg_decay,
                # num_hidden_layers=args.num_hidden_layers,
                eval_epoch = args.eval_epoch,
                optimizer_name=args.optimizer_name,
                clip_gradient=args.clip_gradient,
                loss_func_name = args.loss_func_name,
                hidden_layer_size = args.hidden_layer_size)

    else:
        assert False

REGEX_TEMPLATES = ['10a', '11a', '11b', '3b', '9b', '9a']
def get_query_fns():
    fns = list(glob.glob(args.query_dir + "/*"))
    fns = [fn for fn in fns if os.path.isdir(fn)]
    skipped_templates = []
    train_qfns = []
    test_qfns = []
    val_qfns = []

    if args.no_regex_templates:
        new_templates = []
        for template_dir in fns:
            isregex = False
            for regtmp in REGEX_TEMPLATES:
                if regtmp in template_dir:
                    isregex = True
            if isregex:
                skipped_templates.append(template_dir)
            else:
                new_templates.append(template_dir)
        fns = new_templates

    if args.train_test_split_kind == "template":
        # the train/test split will be on the template names
        sorted_fns = copy.deepcopy(fns)
        sorted_fns.sort()
        train_tmps, test_tmps = train_test_split(sorted_fns,
                test_size=args.test_size,
                random_state=args.diff_templates_seed)

    elif args.train_test_split_kind == "custom":
        train_tmp_names = args.train_tmps.split(",")
        test_tmp_names = args.test_tmps.split(",")
        train_tmps = []
        test_tmps = []
        for fn in fns:
            for ctmp in train_tmp_names:
                if ctmp in fn:
                    train_tmps.append(fn)
                    break

            for ctmp in test_tmp_names:
                if ctmp in fn:
                    test_tmps.append(fn)
                    break

    for qi,qdir in enumerate(fns):
        if ".json" in qdir:
            continue

        template_name = os.path.basename(qdir)
        if args.query_templates != "all":
            query_templates = args.query_templates.split(",")
            if template_name not in query_templates:
                skipped_templates.append(template_name)
                continue
        if args.skip7a and template_name == "7a":
            skipped_templates.append(template_name)
            continue

        # let's first select all the qfns we are going to load
        qfns = list(glob.glob(qdir+"/*.pkl"))
        qfns.sort()

        if args.num_samples_per_template == -1 \
                or args.num_samples_per_template >= len(qfns):
            qfns = qfns
        elif args.num_samples_per_template < len(qfns):
            qfns = qfns[0:args.num_samples_per_template]
        else:
            assert False

        if args.train_test_split_kind == "template":
            cur_val_fns = []
            if qdir in train_tmps:
                cur_train_fns = qfns
                cur_test_fns = []
            elif qdir in test_tmps:
                cur_train_fns = []
                cur_test_fns = qfns
            else:
                continue
                # assert False
        elif args.train_test_split_kind == "custom":
            # cur_val_fns = []
            if qdir in train_tmps:
                # cur_train_fns = qfns
                # cur_test_fns = []
                cur_val_fns, cur_train_fns = train_test_split(qfns,
                        test_size=1-args.val_size,
                        random_state=args.seed)
                cur_test_fns = []
            elif qdir in test_tmps:
                # no validation set from here
                cur_val_fns = []
                cur_train_fns = []
                cur_test_fns = qfns
            else:
                continue

        elif args.train_test_split_kind == "query":
            if args.val_size == 0:
                cur_val_fns = []
            else:
                cur_val_fns, qfns = train_test_split(qfns,
                        test_size=1-args.val_size,
                        random_state=args.seed)

            if args.test_size == 0:
                cur_test_fns = []
                cur_train_fns = qfns
            else:
                cur_train_fns, cur_test_fns = train_test_split(qfns,
                        test_size=args.test_size,
                        random_state=args.seed)

        train_qfns += cur_train_fns
        val_qfns += cur_val_fns
        test_qfns += cur_test_fns

    print("Skipped templates: ", " ".join(skipped_templates))

    if args.train_test_split_kind == "query":
        print("""Selected {} train queries, {} test queries, and {} val queries"""\
                .format(len(train_qfns), len(test_qfns), len(val_qfns)))
    # elif args.train_test_split_kind == "template":
    else:
        train_tmp_names = [os.path.basename(tfn) for tfn in train_tmps]
        test_tmp_names = [os.path.basename(tfn) for tfn in test_tmps]
        print("""Selected {} train queries, {} test queries, and {} val queries"""\
                .format(len(train_qfns), len(test_qfns), len(val_qfns)))
        print("""Selected {} train templates, {} test templates"""\
                .format(len(train_tmp_names), len(test_tmp_names)))
        print("""Training templates: {}\nEvaluation templates: {}""".\
                format(",".join(train_tmp_names), ",".join(test_tmp_names)))

    # going to shuffle all these lists, so queries are evenly distributed. Plan
    # Cost functions for some of these templates take a lot longer; so when we
    # compute them in parallel, we want the queries to be shuffled so the
    # workload is divided evely
    random.shuffle(train_qfns)
    random.shuffle(test_qfns)
    random.shuffle(val_qfns)

    return train_qfns, test_qfns, val_qfns

def load_qdata(fns):
    qreps = []
    for qfn in fns:
        qrep = load_qrep(qfn)

        if args.algs in ["joinkeys", "postgres"]:
            skip = False
            sg = qrep["subset_graph"]
            for u,v,data in sg.edges(data=True):
                if "join_key_cardinality" not in data:
                    # print(data)
                    # print(qfn)
                    # print(u, v)
                    # pdb.set_trace()
                    skip = True
                    break

            if skip:
                continue

        # TODO: can do checks like no queries with zero cardinalities etc.
        qreps.append(qrep)
        template_name = os.path.basename(os.path.dirname(qfn))
        qrep["name"] = os.path.basename(qfn)
        qrep["template_name"] = template_name

    return qreps

def get_featurizer(trainqs, valqs, testqs):
    featurizer = Featurizer(args.user, args.pwd, args.db_name,
            args.db_host, args.port)
    featdata_fn = os.path.join(args.query_dir, "dbdata.json")

    if args.regen_featstats or not os.path.exists(featdata_fn):
        featurizer.update_column_stats(trainqs+valqs+testqs)

        ATTRS_TO_SAVE = ['aliases', 'cmp_ops', 'column_stats', 'joins',
                'max_in_degree', 'max_joins', 'max_out_degree', 'max_preds',
                'max_tables', 'regex_cols', 'tables', 'join_key_stats',
                'primary_join_keys', 'join_key_normalizers',
                'join_key_stat_names', 'join_key_stat_tmps'
                'max_tables', 'regex_cols', 'tables',
                'mcvs']

        featdata = {}
        for k in dir(featurizer):
            if k not in ATTRS_TO_SAVE:
                continue
            attrvals = getattr(featurizer, k)
            if isinstance(attrvals, set):
                attrvals = list(attrvals)
            featdata[k] = attrvals
        f = open(featdata_fn, "w")
        json.dump(featdata, f)
        f.close()
    else:
        f = open(featdata_fn, "r")
        featdata = json.load(f)
        f.close()
        featurizer.update_using_saved_stats(featdata)

    if args.algs == "mscn":
        feat_type = "set"
    else:
        feat_type = "combined"
    # Look at the various keyword arguments to setup() to change the
    # featurization behavior; e.g., include certain features etc.
    # these configuration properties do not influence the basic statistics
    # collected in the featurizer.update_column_stats call; Therefore, we don't
    # include this in the cached version

    featurizer.setup(ynormalization=args.ynormalization,
            sample_bitmap = args.sample_bitmap,
            feat_separate_alias = args.feat_separate_alias,
            onehot_dropout = args.onehot_dropout,
            feat_mcvs = args.feat_mcvs,
            heuristic_features = args.heuristic_features,
            featurization_type=feat_type,
            table_features=args.table_features,
            flow_features = args.flow_features,
            join_features=args.join_features,
            set_column_feature=args.set_column_feature,
            max_discrete_featurizing_buckets=args.max_discrete_featurizing_buckets,
            max_like_featurizing_buckets=args.max_like_featurizing_buckets,
            embedding_fn = args.embedding_fn,
            embedding_pooling = args.embedding_pooling,
            implied_pred_features = args.implied_pred_features,
            feat_onlyseen_preds = args.feat_onlyseen_preds
            )
    featurizer.update_workload_stats(trainqs+valqs+testqs)
    featurizer.init_feature_mapping()
    featurizer.update_ystats(trainqs+valqs+testqs)

    # if args.feat_onlyseen_preds:
    # just do it always
    featurizer.update_seen_preds(trainqs)

    return featurizer

def _get_distr(samples):
    tabs = set()
    cols = set()
    consts = set()

    joins = set()
    joins2 = set()

    subplans = set()
    subplans2 = set()

    for qrep in samples:
        for node,data in qrep["join_graph"].nodes(data=True):
            tabs.add(data["real_name"])
            for ci,col in enumerate(data["pred_cols"]):
                col = ''.join([ck for ck in col if not ck.isdigit()])
                cols.add(col)
                for const in data["pred_vals"][ci]:
                    consts.add(col+str(const))

        for node in qrep["subset_graph"].nodes():
            # in order to remove aliases
            subplans2.add(str(node))
            node = list(node)
            node.sort()
            node = str(node)
            node = ''.join([ck for ck in node if not ck.isdigit()])
            subplans.add(str(node))

        for e in qrep["join_graph"].edges(data=True):
            # TODO: remove ints
            e0 = ''.join([ck for ck in e[0] if not ck.isdigit()])
            e1 = ''.join([ck for ck in e[1] if not ck.isdigit()])
            jointabs = [e0, e1]
            jointabs.sort()
            joins.add(str(jointabs))

            jointabs2 = [e[0], e[1]]
            jointabs2.sort()
            joins2.add(str(jointabs2))

    return tabs,cols,consts,joins,subplans,joins2,subplans2

def main():

    # set up wandb logging metrics
    if args.use_wandb:
        wandb_tags = ["v13"]
        if args.wandb_tags is not None:
            wandb_tags += args.wandb_tags.split(",")
        wandb.init("ceb", config={},
                tags=wandb_tags)
        wandb.config.update(vars(args))

    train_qfns, test_qfns, val_qfns = get_query_fns()

    trainqs = load_qdata(train_qfns)

    # Note: can be quite memory intensive to load them all; might want to just
    # keep around the qfns and load them as needed
    valqs = load_qdata(val_qfns)
    testqs = load_qdata(test_qfns)

    print("""Selected {} train qdata, {} test qdata, and {} val qdata"""\
            .format(len(trainqs), len(testqs), len(valqs)))

    if args.onehot_dropout == -1:
        # traintabs = set()
        traintabs,traincols,trainconsts,trainjoins,trainsubs,trainjoins2, \
            trainsubs2 = _get_distr(trainqs)
        testtabs,testcols,testconsts,testjoins,testsubs, testjoins2, \
            testsubs2 = _get_distr(testqs)

        tabdiff = round(len(testtabs-traintabs) / float(len(testtabs)), 4)
        coldiff = round(len(testcols-traincols) / float(len(testcols)), 4)
        constdiff = round(len(testconsts-trainconsts) / float(len(testconsts)),
                3)
        joindiff = round(len(testjoins-trainjoins) / float(len(testjoins)), 3)
        joindiff2 = round(len(testjoins2-trainjoins2) / float(len(testjoins2)),
                3)

        subdiff = round(len(testsubs-trainsubs) / float(len(testsubs)), 2)
        subdiff2 = round(len(testsubs2-trainsubs2) / float(len(testsubs2)), 2)

        print("""Table: {}, Columns: {}, Const: {}, Joins: {}, Subplans: {},
                 Joins2: {}, Subplans2: {}""".format(
            tabdiff, coldiff, constdiff, joindiff, subdiff, joindiff2, subdiff2))

        print("TabDiff: ", testtabs-traintabs)
        print("ColDiff: ", testcols-traincols)
        print("JoinDiff: ", testjoins-trainjoins)
        # print("SubDiff: ", testsubs-trainsubs)

        testunseensubs = []
        testunseensubs2 = []
        for qrep in testqs:
            for node in qrep["subset_graph"]:
                # subplans2.add(str(node))
                if str(node) not in trainsubs2:
                    testunseensubs2.append(True)
                else:
                    testunseensubs2.append(False)

                node = list(node)
                node.sort()
                node = str(node)
                node = ''.join([ck for ck in node if not ck.isdigit()])
                if node not in trainsubs:
                    testunseensubs.append(True)
                else:
                    testunseensubs.append(False)

        print("Fraction UnseenSubs1: ", np.mean(testunseensubs))
        print("Fraction UnseenSubs2: ", np.mean(testunseensubs2))

        exit(-1)

        # pdb.set_trace()


    # only needs featurizer for learned models
    if args.algs in ["xgb", "fcnn", "mscn"]:
        featurizer = get_featurizer(trainqs, valqs, testqs)
    else:
        featurizer = None

    algs = []
    for alg_name in args.algs.split(","):
        algs.append(get_alg(alg_name))

    eval_fns = []
    for efn in args.eval_fns.split(","):
        eval_fns.append(get_eval_fn(efn))

    for alg in algs:
        alg.train(trainqs, valqs=valqs, testqs=testqs,
                featurizer=featurizer, result_dir=args.result_dir)

        eval_alg(alg, eval_fns, trainqs, "train", featurizer=featurizer)

        if len(valqs) > 0:
            eval_alg(alg, eval_fns, valqs, "val", featurizer=featurizer)

        if len(testqs) > 0:
            eval_alg(alg, eval_fns, testqs, "test", featurizer=featurizer)

# def check_logical_constraints(alg, qreps):
    # for qrep in qreps:
        # for node in qrep["subset_graph"].nodes():
            # pdb.set_trace()

def read_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query_dir", type=str, required=False,
            default="./queries/imdb/")

    ## db credentials
    parser.add_argument("--db_name", type=str, required=False,
            default="imdb")
    parser.add_argument("--db_host", type=str, required=False,
            default="localhost")
    parser.add_argument("--user", type=str, required=False,
            default="ceb")
    # parser.add_argument("--user", type=str, required=False,
            # default="pari")
    parser.add_argument("--pwd", type=str, required=False,
            default="password")
    parser.add_argument("--port", type=int, required=False,
            default=5432)

    parser.add_argument("--result_dir", type=str, required=False,
            default="results")
    parser.add_argument("--query_templates", type=str, required=False,
            default="all")

    parser.add_argument("--seed", type=int, required=False,
            default=123)
    parser.add_argument("--no_regex_templates", type=int,
            required=False, default=0, help="""=1, will skip templates having regex queries""")

    parser.add_argument("--skip7a", type=int, required=False,
            default=0, help="""since 7a  is a template with a very large joingraph, we have a flag to skip it to make things run faster""")
    parser.add_argument("--num_eval_processes", type=int, required=False,
            default=16, help="""Used for computing plan costs in parallel. -1 use all cpus; -2: use no cpus; else use n cpus. """)

    parser.add_argument("--train_test_split_kind", type=str, required=False,
            default="query", help="""query OR template.""")
    parser.add_argument("--diff_templates_seed", type=int, required=False,
            default=1, help="""Seed used when train_test_split_kind == template""")

    parser.add_argument("--train_tmps", type=str, required=False,
            default=None)
    parser.add_argument("--test_tmps", type=str, required=False,
            default=None)

    parser.add_argument("-n", "--num_samples_per_template", type=int,
            required=False, default=-1)
    parser.add_argument("--test_size", type=float, required=False,
            default=0.5)
    parser.add_argument("--val_size", type=float, required=False,
            default=0.2)
    parser.add_argument("--algs", type=str, required=False,
            default="postgres")
    parser.add_argument("--eval_fns", type=str, required=False,
            default="qerr,ppc")

    parser.add_argument("--cost_model", type=str, required=False,
            default="C")
    parser.add_argument("--normalize_flow_loss", type=int, required=False,
            default=1)

    parser.add_argument("--onehot_dropout", type=int, required=False,
            default=0)
    parser.add_argument("--inp_dropout", type=float, required=False,
            default=0.0)
    parser.add_argument("--hl_dropout", type=float, required=False,
            default=0.0)
    parser.add_argument("--comb_dropout", type=float, required=False,
            default=0.0)

    parser.add_argument("--onehot_mask_truep", type=float, required=False,
            default=0.8)

    parser.add_argument("--onehot_reg", type=int, required=False,
            default=0)

    parser.add_argument("--onehot_reg_decay", type=float, required=False,
            default=0.1)
    parser.add_argument("--subplan_level_outputs", type=int, required=False,
            default=0)
    parser.add_argument("--mask_unseen_subplans", type=int, required=False,
            default=0)

    # featurizer arguments
    parser.add_argument("--regen_featstats", type=int, required=False,
            default=0)
    parser.add_argument("--heuristic_features", type=int, required=False,
            default=1)
    parser.add_argument("--ynormalization", type=str, required=False,
            default="log")
    parser.add_argument("--feat_onlyseen_preds", type=int, required=False,
            default=1)
    parser.add_argument("--feat_separate_alias", type=int, required=False,
            default=0)
    parser.add_argument("--heuristic_unseen_preds", type=str, required=False,
            default=None)
    parser.add_argument("--feat_mcvs", type=int, required=False,
            default=0)
    parser.add_argument("--implied_pred_features", type=int, required=False,
            default=0)

    ## NN training features
    parser.add_argument("--load_padded_mscn_feats", type=int, required=False,
            default=1, help="""==1 loads all the mscn features with padded zeros in memory -- speeds up training, but can take too much RAM.""")
    parser.add_argument("--training_opt", type=str, required=False,
            default="")
    parser.add_argument("--opt_lr", type=float, required=False,
            default=0.005)
    parser.add_argument("--swa_start", type=int, required=False,
            default=5)

    parser.add_argument("--weight_decay", type=float, required=False,
            default=0.0)
    parser.add_argument("--max_epochs", type=int,
            required=False, default=10)
    parser.add_argument("--eval_epoch", type=int,
            required=False, default=100)
    parser.add_argument("--mb_size", type=int, required=False,
            default=1024)

    parser.add_argument("--num_hidden_layers", type=int,
            required=False, default=2)
    parser.add_argument("--hidden_layer_size", type=int,
            required=False, default=128)
    parser.add_argument("--load_query_together", type=int, required=False,
            default=0)
    parser.add_argument("--optimizer_name", type=str, required=False,
            default="adamw")
    parser.add_argument("--clip_gradient", type=float,
            required=False, default=20.0)
    parser.add_argument("--lr", type=float,
            required=False, default=0.0001)
    parser.add_argument("--loss_func_name", type=str, required=False,
            default="mse")

    parser.add_argument("--table_features", type=int, required=False,
            default=1)
    parser.add_argument("--join_features", type=str, required=False,
            default="onehot")
    parser.add_argument("--set_column_feature", type=str, required=False,
            default="onehot")
    parser.add_argument("--flow_features", type=int, required=False,
            default=0)

    parser.add_argument("--sample_bitmap", type=int, required=False,
            default=0)
    parser.add_argument("--max_discrete_featurizing_buckets", type=int, required=False,
            default=10)
    parser.add_argument("--max_like_featurizing_buckets", type=int, required=False,
            default=10)

    parser.add_argument("--embedding_fn", type=str, required=False, default=None)
    parser.add_argument("--embedding_pooling", type=str, required=False, default=None)

    parser.add_argument("--save_pdf_plans", type=int, required=False,
            default=0)

    # logging arguments
    parser.add_argument("--wandb_tags", type=str, required=False,
        default=None, help="additional tags for wandb logs")
    parser.add_argument("--use_wandb", type=int, required=False,
        default=1, help="")

    return parser.parse_args()

if __name__ == "__main__":
    args = read_flags()
    main()
